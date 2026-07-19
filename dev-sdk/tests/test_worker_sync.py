"""Tests for worker sync helpers (outbox, origin comms sync)."""

from __future__ import annotations

from pathlib import Path

from dev_sdk.comms import LOGS_DIR, add_comms, comms_dir, index_path, read_index
from dev_sdk.worker_sync import (
    OutboxEntry,
    TailState,
    collect_comms_push_items,
    has_outbox,
    merge_index_after_pull,
    read_outbox,
    repair_local_index,
    sync_task_comms_origin,
    tail_bash_file,
    tail_log_file,
    write_outbox,
)


class FakeSyncClient:
    def __init__(self, pull: list[dict] | None = None) -> None:
        self.pull = pull or []
        self.push_calls: list[list[dict]] = []

    def sync_push(self, task_name: str, items: list[dict]) -> list[dict]:
        self.push_calls.append(items)
        return list(self.pull)


def test_repair_local_index_adds_orphan_files(tmp_path: Path) -> None:
    task = tmp_path / "task-a"
    task.mkdir()
    add_comms(task, "user", "# first")
    orphan = comms_dir(task) / "019-agent-question.md"
    orphan.write_text('{"intro": "x", "questions": []}\n', encoding="utf-8")
    assert "019-agent-question.md" not in read_index(task)

    merged = repair_local_index(task)

    assert "019-agent-question.md" in merged
    assert "019-agent-question.md" in read_index(task)


def test_collect_comms_push_includes_orphans(tmp_path: Path) -> None:
    task = tmp_path / "task-a"
    task.mkdir()
    orphan = comms_dir(task)
    orphan.mkdir(parents=True)
    (orphan / "019-agent-question.md").write_text("orphan\n", encoding="utf-8")

    items = collect_comms_push_items(task)
    names = {item["filename"] for item in items}

    assert "019-agent-question.md" in names
    assert "index.txt" in names


def test_merge_index_preserves_local_only_entries() -> None:
    cloud = ["001-user.md", "002-agent-question.md"]
    local = {"001-user.md", "002-agent-question.md", "019-agent-question.md"}
    merged = merge_index_after_pull(local, cloud)
    assert merged == ["001-user.md", "002-agent-question.md", "019-agent-question.md"]


def test_outbox_roundtrip(tmp_path: Path) -> None:
    task = tmp_path / "task-a"
    task.mkdir()
    write_outbox(task, OutboxEntry(error=None, result={"branch": "main"}, sync_failures=2))
    assert has_outbox(task)
    entry = read_outbox(task)
    assert entry is not None
    assert entry.result["branch"] == "main"
    assert entry.sync_failures == 2


def test_sync_applies_cloud_index_without_dropping_locals(tmp_path: Path) -> None:
    task = tmp_path / "task-a"
    task.mkdir()
    add_comms(task, "user", "# local")
    orphan = comms_dir(task) / "019-agent-question.md"
    orphan.write_text("orphan\n", encoding="utf-8")
    client = FakeSyncClient(
        pull=[
            {"filename": "001-user.md", "content": "# cloud copy", "origin": "cloud"},
            {"filename": "index.txt", "content": "001-user.md\n", "origin": "cloud"},
        ]
    )
    sync_task_comms_origin(client, task, "task-a")
    assert "019-agent-question.md" in read_index(task)
    assert orphan.read_text(encoding="utf-8") == "orphan\n"


class FakeUploadClient:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, bytes, str]] = []

    def upload_log_chunk(
        self,
        task_name: str,
        filename: str,
        chunk: bytes,
        *,
        kind: str = "log",
    ) -> None:
        self.uploads.append((task_name, filename, chunk, kind))


def test_tail_log_file_uploads_incrementally(tmp_path: Path) -> None:
    task = tmp_path / "task-a"
    logs = task / LOGS_DIR
    logs.mkdir(parents=True)
    log_path = logs / "dev-implement.log"
    log_path.write_bytes(b"line1\n")
    client = FakeUploadClient()
    state = TailState()

    state = tail_log_file(client, task, "task-a", "dev-implement.log", state)
    assert state.log_offset == len(b"line1\n")
    assert client.uploads == [("task-a", "dev-implement.log", b"", "log"), ("task-a", "dev-implement.log", b"line1\n", "log")]

    log_path.write_bytes(b"line1\nline2\n")
    state = tail_log_file(client, task, "task-a", "dev-implement.log", state)
    assert state.log_offset == len(b"line1\nline2\n")
    assert client.uploads[-1] == ("task-a", "dev-implement.log", b"line2\n", "log")


def test_tail_bash_file_uploads_incrementally(tmp_path: Path) -> None:
    task = tmp_path / "task-a"
    cdir = comms_dir(task)
    cdir.mkdir(parents=True)
    bash_path = cdir / "001-user-bash.md"
    bash_path.write_bytes(b"out1\n")
    client = FakeUploadClient()
    state = TailState()

    state = tail_bash_file(client, task, "task-a", "001-user-bash.md", state)
    assert state.bash_offset == len(b"out1\n")
    assert client.uploads[-1] == ("task-a", "001-user-bash.md", b"out1\n", "bash")

    bash_path.write_bytes(b"out1\nout2\n")
    state = tail_bash_file(client, task, "task-a", "001-user-bash.md", state)
    assert state.bash_offset == len(b"out1\nout2\n")
    assert client.uploads[-1] == ("task-a", "001-user-bash.md", b"out2\n", "bash")
