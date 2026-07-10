"""Tests for cloud control plane routing."""

from __future__ import annotations

import json
import os

import boto3
import pytest
from moto import mock_aws

from dev_cloud_control.handler import Router
from dev_cloud_control.store import CloudStore


@pytest.fixture
def aws_env():
    with mock_aws():
        os.environ["DEV_CLOUD_TABLE"] = "dev-cloud-test"
        os.environ["DEV_CLOUD_BUCKET"] = "dev-cloud-test-bucket"
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName="dev-cloud-test",
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
                {"AttributeName": "entity", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "entity-index",
                    "KeySchema": [
                        {"AttributeName": "entity", "KeyType": "HASH"},
                        {"AttributeName": "pk", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="dev-cloud-test-bucket")
        yield


def _event(method: str, path: str, body: dict | None = None, *, query: str = "") -> dict:
    ev = {
        "requestContext": {"http": {"method": method}},
        "rawPath": f"/api{path}",
        "rawQueryString": query,
    }
    if body is not None:
        ev["body"] = json.dumps(body)
    return ev


def test_worker_poll_registers_environment(aws_env):
    router = Router()
    resp = router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1"}))
    assert resp["statusCode"] == 200
    data = json.loads(resp["body"])
    assert data["environment_id"] == "env-1"
    assert data["display_name"] == "env-1"[:8]


def test_worker_poll_unique_display_name(aws_env):
    router = Router()
    router.dispatch(
        _event("POST", "/worker/poll", {"environment_id": "env-1", "display_name": "desk"}),
    )
    resp = router.dispatch(
        _event("POST", "/worker/poll", {"environment_id": "env-2", "display_name": "desk"}),
    )
    data = json.loads(resp["body"])
    assert data["display_name"] == "desk-2"


def test_worker_poll_prunes_offline_duplicate(aws_env):
    router = Router()
    store = CloudStore()
    store.register_environment("env-old", "dev-environment")
    # Force offline by backdating heartbeat
    store._table.update_item(
        Key={"pk": "ENV#env-old", "sk": "META"},
        UpdateExpression="SET last_heartbeat = :ts",
        ExpressionAttributeValues={":ts": "1"},
    )
    resp = router.dispatch(
        _event(
            "POST",
            "/worker/poll",
            {"environment_id": "env-live", "display_name": "dev-environment"},
        ),
    )
    assert resp["statusCode"] == 200
    data = json.loads(resp["body"])
    assert data["display_name"] == "dev-environment"
    assert store.get_environment("env-old") is None
    assert store.get_environment("env-live") is not None


def test_create_task_queues_command(aws_env):
    router = Router()
    router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1", "display_name": "Test"}))
    resp = router.dispatch(
        _event(
            "POST",
            "/tasks",
            {"title": "My Task", "environment_id": "env-1", "repo": None},
        )
    )
    assert resp["statusCode"] == 200
    lines = [json.loads(ln) for ln in resp["body"].strip().split("\n") if ln]
    assert any(l["type"] == "complete" for l in lines)
    assert not any(l["type"] == "accepted" for l in lines)
    poll = router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1"}))
    work = json.loads(poll["body"])["work"]
    assert any(w["command"]["command"] == "create-task" for w in work)


def test_repos_crud(aws_env):
    router = Router()
    resp = router.dispatch(_event("POST", "/repos", {"name": "dev", "url": "https://github.com/o/r.git"}))
    assert resp["statusCode"] == 200
    repos = json.loads(router.dispatch(_event("GET", "/repos"))["body"])
    assert repos["dev"] == "https://github.com/o/r.git"


def test_archive_task_updates_status(aws_env):
    router = Router()
    router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1", "display_name": "Main"}))
    router.dispatch(
        _event(
            "POST",
            "/tasks",
            {"title": "Archive me", "environment_id": "env-1", "repo": None},
        )
    )
    create_lines = router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1"}))
    work = json.loads(create_lines["body"])["work"]
    task_name = work[0]["task_name"]
    router.dispatch(
        _event("POST", f"/worker/tasks/{task_name}/command/complete", {"result": {}})
    )
    resp = router.dispatch(_event("POST", f"/tasks/{task_name}/archive"))
    assert resp["statusCode"] == 200
    tasks = json.loads(router.dispatch(_event("GET", "/tasks"))["body"])["tasks"]
    assert task_name not in tasks
    archive = json.loads(router.dispatch(_event("GET", "/archive"))["body"])
    assert any(e["task_name"] == task_name for e in archive["entries"])


def test_cancel_active_command_sets_cancelling_state(aws_env):
    router = Router()
    store = CloudStore()
    router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1", "display_name": "Main"}))
    router.dispatch(
        _event(
            "POST",
            "/tasks",
            {"title": "Cancel me", "environment_id": "env-1", "repo": None},
        )
    )
    poll = router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1"}))
    task_name = json.loads(poll["body"])["work"][0]["task_name"]
    router.dispatch(_event("POST", f"/worker/tasks/{task_name}/command/start"))

    cancel = router.dispatch(_event("POST", f"/tasks/{task_name}/commands/cancel"))
    assert cancel["statusCode"] == 204

    status = json.loads(router.dispatch(_event("GET", f"/tasks/{task_name}/commands"))["body"])
    assert status["active"] is True
    assert status["cancelling"] is True
    assert status["create_progress"][-1] == "Cancelling…"

    task = store.get_task(task_name)
    assert task.active_command["cancelling"] is True
    assert task.active_command["cancel_requested"] is True


def test_cancel_stuck_cancelling_force_clears(aws_env):
    router = Router()
    store = CloudStore()
    router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1", "display_name": "Main"}))
    router.dispatch(
        _event(
            "POST",
            "/tasks",
            {"title": "Stuck", "environment_id": "env-1", "repo": None},
        )
    )
    poll = router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1"}))
    task_name = json.loads(poll["body"])["work"][0]["task_name"]
    router.dispatch(_event("POST", f"/tasks/{task_name}/commands/cancel"))
    router.dispatch(_event("POST", f"/tasks/{task_name}/commands/cancel"))

    status = json.loads(router.dispatch(_event("GET", f"/tasks/{task_name}/commands"))["body"])
    assert status["active"] is False
    assert status["command"] is None
    assert status["cancelling"] is False
    assert status["command_error"] == "Cancelled"
    task = store.get_task(task_name)
    assert task.active_command is None
    assert task.last_command_error == "Cancelled"


def test_command_status_shows_queued_create_task(aws_env):
    router = Router()
    router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1", "display_name": "Main"}))
    router.dispatch(
        _event(
            "POST",
            "/tasks",
            {"title": "Queued", "environment_id": "env-1", "repo": None},
        )
    )
    task_name = json.loads(router.dispatch(_event("GET", "/tasks"))["body"])["tasks"][0]
    status = json.loads(router.dispatch(_event("GET", f"/tasks/{task_name}/commands"))["body"])
    assert status["queued"] is True
    assert status["active"] is False
    assert status["command"] == "create-task"
    assert status["cancelling"] is False


def test_worker_upload_log_empty_chunk_registers_feed(aws_env):
    import base64

    router = Router()
    store = CloudStore()
    router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1", "display_name": "Main"}))
    router.dispatch(
        _event(
            "POST",
            "/tasks",
            {"title": "Log test", "environment_id": "env-1", "repo": None},
        )
    )
    poll = router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1"}))
    task_name = json.loads(poll["body"])["work"][0]["task_name"]
    log_name = "dev-question-stream-20260703-161500.log"

    resp = router.dispatch(
        _event(
            "POST",
            f"/worker/tasks/{task_name}/logs",
            {"filename": log_name, "chunk_b64": ""},
        )
    )
    assert resp["statusCode"] == 204

    task = store.get_task(task_name)
    assert task.active_command["active_log_filename"] == log_name
    feed = store.list_feed_items(task_name)
    assert any(f.type == "log" and f.id == log_name for f in feed)

    resp2 = router.dispatch(
        _event(
            "POST",
            f"/worker/tasks/{task_name}/logs",
            {"filename": log_name, "chunk_b64": base64.b64encode(b"line1\n").decode("ascii")},
        )
    )
    assert resp2["statusCode"] == 204
    content = store.get_log(task_name, log_name)
    assert content == "line1\n"


def test_task_stream_emits_log_and_reconnect(aws_env):
    import base64

    router = Router()
    store = CloudStore()
    router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1", "display_name": "Main"}))
    router.dispatch(
        _event(
            "POST",
            "/tasks",
            {"title": "Stream test", "environment_id": "env-1", "repo": None},
        )
    )
    poll = router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1"}))
    task_name = json.loads(poll["body"])["work"][0]["task_name"]
    log_name = "dev-question-stream-20260703-161500.log"
    router.dispatch(
        _event(
            "POST",
            f"/worker/tasks/{task_name}/logs",
            {"filename": log_name, "chunk_b64": base64.b64encode(b"live\n").decode("ascii")},
        )
    )
    ev = _event("GET", f"/tasks/{task_name}/stream", query="stream_duration=0.5")
    resp = router.dispatch(ev)
    assert resp["statusCode"] == 200
    assert resp["headers"]["Content-Type"] == "text/event-stream"
    assert "event: log" in resp["body"]
    assert "live" in resp["body"]
    assert "event: reconnect" in resp["body"]


def test_worker_upload_bash_stream(aws_env):
    import base64

    router = Router()
    store = CloudStore()
    router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1", "display_name": "Main"}))
    router.dispatch(
        _event(
            "POST",
            "/tasks",
            {"title": "Bash stream", "environment_id": "env-1", "repo": None},
        )
    )
    poll = router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1"}))
    task_name = json.loads(poll["body"])["work"][0]["task_name"]
    bash_name = "001-user-bash.md"
    router.dispatch(
        _event(
            "POST",
            f"/worker/tasks/{task_name}/logs",
            {
                "filename": bash_name,
                "kind": "bash",
                "chunk_b64": base64.b64encode(b"output\n").decode("ascii"),
            },
        )
    )
    data, total = store.read_stream_from_offset(task_name, "bash", bash_name, 0)
    assert data.decode("utf-8") == "output\n"
    assert total == len(b"output\n")


def test_comms_sync_blocks_command_until_worker_pulls(aws_env):
    router = Router()
    store = CloudStore()
    router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1", "display_name": "Main"}))
    router.dispatch(
        _event(
            "POST",
            "/tasks",
            {"title": "Sync gate", "environment_id": "env-1", "repo": None},
        )
    )
    task_name = json.loads(router.dispatch(_event("GET", "/tasks"))["body"])["tasks"][0]
    router.dispatch(_event("POST", f"/worker/tasks/{task_name}/sync", {"push": []}))
    poll = router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1"}))
    assert poll["statusCode"] == 200
    router.dispatch(
        _event("POST", f"/worker/tasks/{task_name}/command/complete", {"result": {}})
    )
    router.dispatch(
        _event(
            "POST",
            f"/tasks/{task_name}/comms/question-answers",
            {
                "source": "001-agent-question.md",
                "answers": [{"id": "q1", "text": "Q?", "selected": "A", "free_text": ""}],
            },
        )
    )
    router.dispatch(_event("POST", f"/tasks/{task_name}/commands", {"command": "question"}))
    status = json.loads(router.dispatch(_event("GET", f"/tasks/{task_name}/commands"))["body"])
    assert status["command"] == "question"
    assert status["active"] is False
    assert status["pending_state"] == "syncing"
    no_work = router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1"}))
    assert json.loads(no_work["body"])["work"] == []
    router.dispatch(_event("POST", f"/worker/tasks/{task_name}/sync", {"push": []}))
    task = store.get_task(task_name)
    assert task.worker_comms_epoch >= task.comms_cloud_epoch
    work = router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1"}))
    assert len(json.loads(work["body"])["work"]) == 1


def test_worker_sync_pulls_comms_index(aws_env):
    router = Router()
    router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1", "display_name": "Main"}))
    router.dispatch(
        _event(
            "POST",
            "/tasks",
            {"title": "Index sync", "environment_id": "env-1", "repo": None},
        )
    )
    task_name = json.loads(router.dispatch(_event("GET", "/tasks"))["body"])["tasks"][0]
    router.dispatch(_event("POST", f"/worker/tasks/{task_name}/sync", {"push": []}))
    answers_resp = router.dispatch(
        _event(
            "POST",
            f"/tasks/{task_name}/comms/question-answers",
            {
                "source": "001-agent-question.md",
                "answers": [{"id": "q1", "text": "Q?", "selected": "A", "free_text": ""}],
            },
        )
    )
    answers_filename = json.loads(answers_resp["body"])["filename"]
    sync = json.loads(
        router.dispatch(_event("POST", f"/worker/tasks/{task_name}/sync", {"push": []}))["body"]
    )
    pull = sync["pull"]
    pulled_names = {p["filename"] for p in pull}
    assert answers_filename in pulled_names
    index_item = next((p for p in pull if p["filename"] == "index.txt"), None)
    assert index_item is not None
    assert answers_filename in index_item["content"]


def _make_offline(store: CloudStore, environment_id: str) -> None:
    store._table.update_item(
        Key={"pk": f"ENV#{environment_id}", "sk": "META"},
        UpdateExpression="SET last_heartbeat = :ts",
        ExpressionAttributeValues={":ts": "1"},
    )


def test_cancel_active_command_when_worker_offline_instant_clears(aws_env):
    router = Router()
    store = CloudStore()
    router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1", "display_name": "Main"}))
    router.dispatch(
        _event(
            "POST",
            "/tasks",
            {"title": "Offline cancel", "environment_id": "env-1", "repo": None},
        )
    )
    poll = router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1"}))
    task_name = json.loads(poll["body"])["work"][0]["task_name"]
    router.dispatch(_event("POST", f"/worker/tasks/{task_name}/command/start"))
    _make_offline(store, "env-1")

    cancel = router.dispatch(_event("POST", f"/tasks/{task_name}/commands/cancel"))
    assert cancel["statusCode"] == 204

    status = json.loads(router.dispatch(_event("GET", f"/tasks/{task_name}/commands"))["body"])
    assert status["active"] is False
    assert status["cancelling"] is False
    assert status["command_error"] == "Cancelled"
    task = store.get_task(task_name)
    assert task.active_command is None
    assert task.last_command_error == "Cancelled"


def test_command_status_auto_clears_cancelling_when_worker_offline(aws_env):
    router = Router()
    store = CloudStore()
    router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1", "display_name": "Main"}))
    router.dispatch(
        _event(
            "POST",
            "/tasks",
            {"title": "Grace cancel", "environment_id": "env-1", "repo": None},
        )
    )
    poll = router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1"}))
    task_name = json.loads(poll["body"])["work"][0]["task_name"]
    router.dispatch(_event("POST", f"/worker/tasks/{task_name}/command/start"))
    router.dispatch(_event("POST", f"/tasks/{task_name}/commands/cancel"))

    status = json.loads(router.dispatch(_event("GET", f"/tasks/{task_name}/commands"))["body"])
    assert status["cancelling"] is True

    _make_offline(store, "env-1")
    status = json.loads(router.dispatch(_event("GET", f"/tasks/{task_name}/commands"))["body"])
    assert status["active"] is False
    assert status["cancelling"] is False
    assert status["command_error"] == "Cancelled"
    task = store.get_task(task_name)
    assert task.active_command is None


def test_command_status_shows_worker_offline_for_started_command(aws_env):
    router = Router()
    store = CloudStore()
    router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1", "display_name": "Main"}))
    router.dispatch(
        _event(
            "POST",
            "/tasks",
            {"title": "Offline running", "environment_id": "env-1", "repo": None},
        )
    )
    poll = router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1"}))
    task_name = json.loads(poll["body"])["work"][0]["task_name"]
    router.dispatch(_event("POST", f"/worker/tasks/{task_name}/command/start"))
    _make_offline(store, "env-1")

    status = json.loads(router.dispatch(_event("GET", f"/tasks/{task_name}/commands"))["body"])
    assert status["active"] is True
    assert status["pending_state"] == "worker_offline"


def test_worker_poll_redelivers_claimed_not_started_command(aws_env):
    router = Router()
    store = CloudStore()
    router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1", "display_name": "Main"}))
    router.dispatch(
        _event(
            "POST",
            "/tasks",
            {"title": "Retry claim", "environment_id": "env-1", "repo": None},
        )
    )
    poll = router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1"}))
    task_name = json.loads(poll["body"])["work"][0]["task_name"]
    router.dispatch(_event("POST", f"/worker/tasks/{task_name}/sync", {"push": []}))

    retry_poll = router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1"}))
    data = json.loads(retry_poll["body"])
    assert len(data["work"]) == 1
    assert data["work"][0]["task_name"] == task_name
    assert data["work"][0]["command"]["command"] == "create-task"
    assert data["work"][0]["command"]["started"] is False
    assert data["active_commands"] == []


def test_worker_poll_returns_active_commands_for_started_commands(aws_env):
    router = Router()
    router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1", "display_name": "Main"}))
    router.dispatch(
        _event(
            "POST",
            "/tasks",
            {"title": "Started orphan", "environment_id": "env-1", "repo": None},
        )
    )
    poll = router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1"}))
    task_name = json.loads(poll["body"])["work"][0]["task_name"]
    router.dispatch(_event("POST", f"/worker/tasks/{task_name}/command/start"))

    poll2 = router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1"}))
    data = json.loads(poll2["body"])
    assert data["work"] == []
    assert len(data["active_commands"]) == 1
    assert data["active_commands"][0]["task_name"] == task_name
    assert data["active_commands"][0]["command"]["started"] is True


def test_worker_command_complete_orphan_with_reboot_message(aws_env):
    router = Router()
    store = CloudStore()
    router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1", "display_name": "Main"}))
    router.dispatch(
        _event(
            "POST",
            "/tasks",
            {"title": "Orphan complete", "environment_id": "env-1", "repo": None},
        )
    )
    poll = router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1"}))
    task_name = json.loads(poll["body"])["work"][0]["task_name"]
    router.dispatch(_event("POST", f"/worker/tasks/{task_name}/command/start"))

    from dev_cloud_control.handler import WORKER_REBOOT_MESSAGE

    router.dispatch(
        _event(
            "POST",
            f"/worker/tasks/{task_name}/command/complete",
            {"error": WORKER_REBOOT_MESSAGE},
        )
    )
    status = json.loads(router.dispatch(_event("GET", f"/tasks/{task_name}/commands"))["body"])
    assert status["active"] is False
    assert status["command_error"] == WORKER_REBOOT_MESSAGE
    task = store.get_task(task_name)
    assert task.active_command is None
    assert task.last_command_error == WORKER_REBOOT_MESSAGE
