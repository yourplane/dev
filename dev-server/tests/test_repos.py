"""Tests for repos API (add/remove shorthands)."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from dev_server.main import app


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    (tmp_path / "dev").mkdir(parents=True, exist_ok=True)
    return tmp_path / "dev" / "repos.json"


@pytest.fixture
def client_with_config(config_file: Path) -> TestClient:
    """TestClient with repo config pointed at tmp_path."""
    with patch("dev_sdk.repo_config.CONFIG_FILE", config_file):
        yield TestClient(app)


def test_get_repos_empty(client_with_config: TestClient) -> None:
    resp = client_with_config.get("/repos")
    assert resp.status_code == 200
    assert resp.json() == {}


def test_post_repos_adds_and_returns_mapping(client_with_config: TestClient, config_file: Path) -> None:
    resp = client_with_config.post(
        "/repos",
        json={"name": "desk", "url": "https://github.com/maxrademacher/desk.git"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"desk": "https://github.com/maxrademacher/desk.git"}
    assert config_file.exists()
    assert "desk" in config_file.read_text()


def test_post_repos_updates_existing(client_with_config: TestClient, config_file: Path) -> None:
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text('{"desk": "https://old.example.com/desk.git"}')
    resp = client_with_config.post(
        "/repos",
        json={"name": "desk", "url": "https://github.com/maxrademacher/desk.git"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"desk": "https://github.com/maxrademacher/desk.git"}


def test_delete_repos_removes_shorthand(client_with_config: TestClient, config_file: Path) -> None:
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text('{"desk": "https://github.com/maxrademacher/desk.git"}')
    resp = client_with_config.delete("/repos/desk")
    assert resp.status_code == 204
    get_resp = client_with_config.get("/repos")
    assert get_resp.json() == {}


def test_delete_repos_missing_returns_404(client_with_config: TestClient) -> None:
    resp = client_with_config.delete("/repos/nonexistent")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


def test_post_repos_invalid_name_rejected(client_with_config: TestClient) -> None:
    resp = client_with_config.post(
        "/repos",
        json={"name": "", "url": "https://github.com/user/repo.git"},
    )
    assert resp.status_code == 400
    assert "Name" in resp.json()["detail"]

    resp2 = client_with_config.post(
        "/repos",
        json={"name": "has/slash", "url": "https://github.com/user/repo.git"},
    )
    assert resp2.status_code == 400
    assert "Name" in resp2.json()["detail"]


def test_post_repos_invalid_url_rejected(client_with_config: TestClient) -> None:
    resp = client_with_config.post(
        "/repos",
        json={"name": "ok", "url": "not-a-url"},
    )
    assert resp.status_code == 400
    assert "URL" in resp.json()["detail"]
