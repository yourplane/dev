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


def _event(method: str, path: str, body: dict | None = None) -> dict:
    ev = {
        "requestContext": {"http": {"method": method}},
        "rawPath": f"/api{path}",
        "rawQueryString": "",
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
    assert any(l["type"] == "accepted" for l in lines)
    assert not any(l["type"] == "complete" for l in lines)
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
