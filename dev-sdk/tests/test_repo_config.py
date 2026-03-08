"""Tests for repo shorthand config."""

from pathlib import Path
from unittest.mock import patch

import pytest

from dev_sdk.repo_config import load_repos, resolve_repo, save_repos


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    return tmp_path / "repos.json"


def test_load_repos_missing_returns_empty(config_file: Path) -> None:
    with patch("dev_sdk.repo_config.CONFIG_FILE", config_file):
        assert load_repos() == {}


def test_load_repos_returns_mapping(config_file: Path) -> None:
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text('{"desk": "https://github.com/maxrademacher/desk.git"}')
    with patch("dev_sdk.repo_config.CONFIG_FILE", config_file):
        assert load_repos() == {"desk": "https://github.com/maxrademacher/desk.git"}


def test_save_repos_creates_file(config_file: Path) -> None:
    with patch("dev_sdk.repo_config.CONFIG_FILE", config_file):
        save_repos({"desk": "https://github.com/maxrademacher/desk.git"})
    assert config_file.exists()
    assert "desk" in config_file.read_text()


def test_resolve_repo_url_passthrough() -> None:
    url = "https://github.com/user/repo.git"
    assert resolve_repo(url) == url
    assert resolve_repo("git@github.com:user/repo.git") == "git@github.com:user/repo.git"


def test_resolve_repo_shorthand_lookup(config_file: Path) -> None:
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text('{"desk": "https://github.com/maxrademacher/desk.git"}')
    with patch("dev_sdk.repo_config.CONFIG_FILE", config_file):
        assert resolve_repo("desk") == "https://github.com/maxrademacher/desk.git"


def test_resolve_repo_unknown_shorthand_raises(config_file: Path) -> None:
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("{}")
    with patch("dev_sdk.repo_config.CONFIG_FILE", config_file):
        with pytest.raises(ValueError, match="Unknown repo shorthand"):
            resolve_repo("unknown")
