"""Tests for create-pr command."""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dev.commands.create_pr import create_pr
from dev_sdk.create_pr import _parse_owner_repo


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_parse_owner_repo_https() -> None:
    assert _parse_owner_repo("https://github.com/owner/repo.git") == ("owner", "repo")
    assert _parse_owner_repo("https://github.com/owner/repo") == ("owner", "repo")
    assert _parse_owner_repo("https://user@github.com/foo/bar.git") == ("foo", "bar")


def test_parse_owner_repo_ssh() -> None:
    assert _parse_owner_repo("git@github.com:owner/repo.git") == ("owner", "repo")
    assert _parse_owner_repo("git@github.com:foo/bar") == ("foo", "bar")


def test_parse_owner_repo_invalid() -> None:
    with pytest.raises(ValueError, match="Cannot parse"):
        _parse_owner_repo("https://gitlab.com/owner/repo.git")
    with pytest.raises(ValueError, match="Cannot parse"):
        _parse_owner_repo("not-a-url")


def test_create_pr_requires_task_root(runner: CliRunner, tmp_path: Path) -> None:
    """Fails when directory has no comms/ (not a task root)."""
    tmp_path.mkdir(exist_ok=True)
    result = runner.invoke(create_pr, ["--task", str(tmp_path)])
    assert result.exit_code != 0
    assert "Not a task root" in result.output or "comms" in result.output


def test_create_pr_requires_single_git_repo(runner: CliRunner, tmp_path: Path) -> None:
    """Fails when no git repo under task root."""
    (tmp_path / "comms").mkdir(parents=True)
    (tmp_path / "comms" / "index.txt").write_text("")
    result = runner.invoke(create_pr, ["--task", str(tmp_path)])
    assert result.exit_code != 0
    assert "No git repository" in result.output


def test_create_pr_rejects_main(
    runner: CliRunner, tmp_path: Path
) -> None:
    """Fails when current branch is main."""
    (tmp_path / "comms").mkdir(parents=True)
    (tmp_path / "comms" / "index.txt").write_text("")
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess_run = subprocess_run_mock(
        repo_root=repo_dir,
        branch="main",
        porcelain="",
        upstream_ok=False,  # we never get to upstream check
    )
    with patch("dev_sdk.create_pr.subprocess.run", subprocess_run):
        result = runner.invoke(create_pr, ["--task", str(tmp_path)])
    assert result.exit_code != 0
    assert "feature branch" in result.output or "not main" in result.output.lower()


def test_create_pr_rejects_dirty_tree(
    runner: CliRunner, tmp_path: Path
) -> None:
    """Fails when working tree has uncommitted changes."""
    (tmp_path / "comms").mkdir(parents=True)
    (tmp_path / "comms" / "index.txt").write_text("")
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess_run = subprocess_run_mock(
        repo_root=repo_dir,
        branch="feature",
        porcelain=" M file.txt",
        upstream_ok=True,
    )
    with patch("dev_sdk.create_pr.subprocess.run", subprocess_run):
        result = runner.invoke(create_pr, ["--task", str(tmp_path)])
    assert result.exit_code != 0
    assert "Uncommitted" in result.output or "commit or stash" in result.output


def test_create_pr_fails_when_push_fails_no_upstream(
    runner: CliRunner, tmp_path: Path
) -> None:
    """Fails when branch has no upstream and git push -u fails."""
    (tmp_path / "comms").mkdir(parents=True)
    (tmp_path / "comms" / "index.txt").write_text("")
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    run_mock = subprocess_run_mock(
        repo_root=repo_dir,
        branch="feature",
        porcelain="",
        upstream_ok=False,
        push_succeeds=False,
    )
    with patch("dev_sdk.create_pr.subprocess.run", side_effect=run_mock):
        result = runner.invoke(create_pr, ["--task", str(tmp_path)])
    assert result.exit_code != 0
    assert "Failed to push" in result.output


def test_create_pr_sets_upstream_when_no_upstream(
    runner: CliRunner, tmp_path: Path
) -> None:
    """When branch has no upstream, runs git push -u then creates PR."""
    (tmp_path / "comms").mkdir(parents=True)
    (tmp_path / "comms" / "index.txt").write_text("")
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    pr_response = {
        "html_url": "https://github.com/owner/repo/pull/99",
        "number": 99,
        "title": tmp_path.name,
    }

    def run(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        return subprocess_run_mock(
            repo_root=repo_dir,
            branch="feature",
            porcelain="",
            upstream_ok=False,
            push_succeeds=True,
        )(*args, **kwargs)

    def urlopen(req):
        body = json.loads(req.data.decode())
        assert body["head"] == "feature"
        response = MagicMock()
        response.status = 201
        response.read.return_value = json.dumps(pr_response).encode()
        response.__enter__ = lambda self: self
        response.__exit__ = lambda *a: None
        return response

    with patch("dev_sdk.create_pr._secret_name_for_github_owner", return_value="dummy-secret"):
        with patch("dev_sdk.create_pr._get_github_token", return_value="secret"):
            with patch("dev_sdk.create_pr.subprocess.run", side_effect=run):
                with patch(
                    "dev_sdk.create_pr.urllib.request.urlopen",
                    side_effect=urlopen,
                ):
                    result = runner.invoke(create_pr, ["--task", str(tmp_path)])
    assert result.exit_code == 0
    assert "https://github.com/owner/repo/pull/99" in result.output


def test_create_pr_pushes_when_out_of_sync(
    runner: CliRunner, tmp_path: Path
) -> None:
    """When branch has upstream but local != remote, runs git push then creates PR."""
    (tmp_path / "comms").mkdir(parents=True)
    (tmp_path / "comms" / "index.txt").write_text("")
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    pr_response = {
        "html_url": "https://github.com/owner/repo/pull/11",
        "number": 11,
        "title": tmp_path.name,
    }

    def run(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        return subprocess_run_mock(
            repo_root=repo_dir,
            branch="feature",
            porcelain="",
            upstream_ok=True,
            push_succeeds=True,
            remote_sha="def456",  # differs from local abc123
        )(*args, **kwargs)

    def urlopen(req):
        body = json.loads(req.data.decode())
        assert body["head"] == "feature"
        response = MagicMock()
        response.status = 201
        response.read.return_value = json.dumps(pr_response).encode()
        response.__enter__ = lambda self: self
        response.__exit__ = lambda *a: None
        return response

    with patch("dev_sdk.create_pr._secret_name_for_github_owner", return_value="dummy-secret"):
        with patch("dev_sdk.create_pr._get_github_token", return_value="secret"):
            with patch("dev_sdk.create_pr.subprocess.run", side_effect=run):
                with patch(
                    "dev_sdk.create_pr.urllib.request.urlopen",
                    side_effect=urlopen,
                ):
                    result = runner.invoke(create_pr, ["--task", str(tmp_path)])
    assert result.exit_code == 0
    assert "https://github.com/owner/repo/pull/11" in result.output


def subprocess_run_mock(
    *,
    repo_root: Path,
    branch: str = "feature",
    porcelain: str = "",
    upstream_ok: bool = True,
    remote_url: str = "https://github.com/owner/repo.git",
    push_succeeds: bool = True,
    remote_sha: str | None = None,
):
    """Build a subprocess.run mock for create_pr git calls."""

    def run(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        cwd = kwargs.get("cwd", Path("."))
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        if cmd[:2] == ["git", "rev-parse"]:
            if "--show-toplevel" in cmd:
                if Path(cwd).resolve() != Path(repo_root).resolve():
                    raise subprocess.CalledProcessError(1, cmd)
                result.stdout = str(repo_root) + "\n"
            elif "--abbrev-ref" in cmd and "HEAD" in cmd:
                result.stdout = branch + "\n"
            elif "@{u}" in cmd:
                if "--abbrev-ref" in cmd:
                    if not upstream_ok:
                        raise subprocess.CalledProcessError(1, cmd)
                    result.stdout = "origin/" + branch + "\n"
                else:
                    result.stdout = (remote_sha or "abc123") + "\n"
            elif "HEAD" in cmd or "origin/main" in str(cmd):
                result.stdout = "abc123\n"
        elif cmd == ["git", "status", "--porcelain"]:
            result.stdout = porcelain
        elif "remote" in cmd and "get-url" in cmd:
            result.stdout = remote_url + "\n"
        elif cmd[:2] == ["git", "log"]:
            result.stdout = "---\nSubject\nBody\n"
        elif cmd[:2] == ["git", "push"]:
            result.returncode = 0 if push_succeeds else 1
            result.stderr = "Failed to push" if not push_succeeds else ""
        return result

    return run


def test_create_pr_success(runner: CliRunner, tmp_path: Path) -> None:
    """With all checks passing and mocked API, prints PR URL."""
    (tmp_path / "comms").mkdir(parents=True)
    (tmp_path / "comms" / "index.txt").write_text("")
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()
    pr_response = {
        "html_url": "https://github.com/owner/repo/pull/42",
        "number": 42,
        "title": tmp_path.name,
    }

    def run(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        return subprocess_run_mock(
            repo_root=repo_dir,
            branch="feature",
            porcelain="",
            upstream_ok=True,
        )(*args, **kwargs)

    def urlopen(req):
        assert req.get_header("Authorization") == "token secret"
        body = json.loads(req.data.decode())
        assert body["base"] == "main"
        assert body["head"] == "feature"
        assert body["title"] == tmp_path.name
        response = MagicMock()
        response.status = 201
        response.read.return_value = json.dumps(pr_response).encode()
        response.__enter__ = lambda self: self
        response.__exit__ = lambda *a: None
        return response

    with patch("dev_sdk.create_pr._secret_name_for_github_owner", return_value="dummy-secret"):
        with patch("dev_sdk.create_pr._get_github_token", return_value="secret"):
            with patch("dev_sdk.create_pr.subprocess.run", side_effect=run):
                with patch(
                    "dev_sdk.create_pr.urllib.request.urlopen",
                    side_effect=urlopen,
                ):
                    result = runner.invoke(create_pr, ["--task", str(tmp_path)])
    assert result.exit_code == 0
    assert "https://github.com/owner/repo/pull/42" in result.output
    assert "#42" in result.output
