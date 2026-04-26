"""Tests for archive listing pagination."""

import os
from pathlib import Path

from fastapi.testclient import TestClient

from dev_server.main import app


def test_archive_list_paginates_newest_first(tmp_path: Path) -> None:
    tasks_root = tmp_path / "tasks"
    archive_root = tasks_root / ".archive"
    archive_root.mkdir(parents=True)

    newest = archive_root / "newer-mar-14-aaaaaa"
    older = archive_root / "older-mar-14-bbbbbb"
    newest.mkdir()
    older.mkdir()
    os.utime(older, (1000, 1000))
    os.utime(newest, (2000, 2000))

    with TestClient(app) as client:
        old = os.environ.get("DEV_TASKS_DIR")
        os.environ["DEV_TASKS_DIR"] = str(tasks_root)
        try:
            first = client.get("/archive", params={"limit": 1, "offset": 0})
            assert first.status_code == 200
            first_body = first.json()
            assert first_body["total"] == 2
            assert first_body["next_offset"] == 1
            assert first_body["entries"][0]["task_name"] == "newer"

            second = client.get("/archive", params={"limit": 1, "offset": 1})
            assert second.status_code == 200
            second_body = second.json()
            assert second_body["total"] == 2
            assert second_body["next_offset"] is None
            assert second_body["entries"][0]["task_name"] == "older"
        finally:
            if old is None:
                os.environ.pop("DEV_TASKS_DIR", None)
            else:
                os.environ["DEV_TASKS_DIR"] = old
