"""Tests for dev-sdk storage abstractions."""

from pathlib import Path

from dev_sdk.comms import add_comms, read_index
from dev_sdk.storage import DraftsStore, LocalFilesystemStorage


def test_local_storage_comms(tmp_path: Path):
    storage = LocalFilesystemStorage(tmp_path)
    task_name = "t1"
    storage.write_comms_file(task_name, "001-user.md", "# hello\n")
    storage.append_comms_index(task_name, "001-user.md")
    assert storage.read_comms_file(task_name, "001-user.md") == "# hello\n"
    assert read_index(storage.task_dir(task_name)) == ["001-user.md"]


def test_drafts_store(tmp_path: Path):
    drafts = DraftsStore(tmp_path)
    drafts.set_new_task_draft(title="x", repo="dev", comment="c")
    data = drafts.get_new_task_draft()
    assert data is not None
    assert data["title"] == "x"
