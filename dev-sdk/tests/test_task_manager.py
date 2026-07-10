"""Tests for TaskManager."""

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dev_sdk.comms import read_index
from dev_sdk.task_manager import TaskCancelled, TaskManager


@pytest.fixture
def tmp_tasks_root(tmp_path: Path) -> Path:
    return tmp_path / "tasks"


@pytest.fixture
def manager(tmp_tasks_root: Path) -> TaskManager:
    return TaskManager(tasks_root=tmp_tasks_root)


class _FakeProc:
    """Minimal stand-in for subprocess.Popen used by TaskManager tests."""

    def __init__(
        self,
        *,
        stdout_lines: list[str] | None = None,
        returncode: int = 0,
        stderr: str = "",
        stdout_bytes: bytes = b"",
        stderr_bytes: bytes = b"",
        on_start: "callable[[], None] | None" = None,
    ) -> None:
        self._stdout_lines = list(stdout_lines or [])
        self.returncode = returncode
        self.stderr = _FakeStream(stderr)
        self.stdout = _FakeStream("".join(self._stdout_lines))
        self._stdout_bytes = stdout_bytes
        self._stderr_bytes = stderr_bytes
        self._killed = False
        self._on_start = on_start

    def start_side_effects(self) -> None:
        if self._on_start:
            self._on_start()

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def terminate(self) -> None:
        self._killed = True

    def kill(self) -> None:
        self._killed = True

    def communicate(self, timeout: float | None = None):
        return self._stdout_bytes, self._stderr_bytes


class _FakeStream:
    def __init__(self, text: str) -> None:
        self._buf = text.splitlines(keepends=True) if text else []
        self._full = text

    def readline(self) -> str:
        if self._buf:
            return self._buf.pop(0)
        return ""

    def read(self) -> str:
        return self._full


def _popen_factory(cases: dict[tuple[str, ...], _FakeProc]):
    def factory(cmd, **kwargs):
        key = tuple(cmd)
        for pattern, proc in cases.items():
            if all(p in key for p in pattern):
                proc.start_side_effects()
                return proc
        raise NotImplementedError(f"Unexpected subprocess: {cmd}")

    return factory


def test_parse_chat_id_single_line(manager: TaskManager) -> None:
    assert manager._parse_chat_id("abc-123-uuid") == "abc-123-uuid"


def test_parse_chat_id_multiple_lines(manager: TaskManager) -> None:
    output = "Some header\nChat created.\nabc-123-uuid"
    assert manager._parse_chat_id(output) == "abc-123-uuid"


def test_parse_chat_id_empty_raises(manager: TaskManager) -> None:
    with pytest.raises(ValueError, match="No output"):
        manager._parse_chat_id("")


def test_ensure_comms_dir_creates_comms_and_rule(manager: TaskManager, tmp_tasks_root: Path) -> None:
    task_dir = tmp_tasks_root / "my-task"
    task_dir.mkdir(parents=True)
    manager._ensure_comms_dir(task_dir)
    assert (task_dir / "comms").is_dir()
    rule_path = task_dir / ".cursor" / "rules" / "task-comms.mdc"
    assert rule_path.exists()
    assert "comms" in rule_path.read_text() and "index.txt" in rule_path.read_text()


def test_write_chat_id_file(manager: TaskManager, tmp_tasks_root: Path) -> None:
    task_dir = tmp_tasks_root / "my-task"
    task_dir.mkdir(parents=True)
    manager._write_chat_id_file(task_dir, "chat-uuid-123")
    path = task_dir / "agent-chat-id"
    assert path.read_text().strip() == "chat-uuid-123"


def _start_task_cases(tmp_tasks_root: Path, task_name: str = "my-task", chat_id: str = "my-chat-id-456") -> dict:
    return {
        ("cursor", "create-chat"): _FakeProc(stdout_lines=[f"{chat_id}\n"]),
        ("git", "clone"): _FakeProc(
            on_start=lambda: (tmp_tasks_root / task_name / "repo").mkdir(parents=True)
        ),
        ("git", "checkout"): _FakeProc(),
    }


@patch("dev_sdk.task_manager.subprocess.Popen")
def test_start_task(
    mock_popen: MagicMock,
    manager: TaskManager,
    tmp_tasks_root: Path,
) -> None:
    mock_popen.side_effect = _popen_factory(_start_task_cases(tmp_tasks_root))

    manager.start_task(
        title="My Task",
        task_name="my-task",
        comment="Build the feature.",
        repo_url="https://github.com/user/repo.git",
    )

    task_dir = tmp_tasks_root / "my-task"
    assert (task_dir / "comms").is_dir()
    assert (task_dir / ".cursor" / "rules" / "task-comms.mdc").exists()
    order = read_index(task_dir)
    assert len(order) == 1
    first = task_dir / "comms" / order[0]
    assert "My Task" in first.read_text() and "Build the feature" in first.read_text()
    assert (task_dir / "agent-chat-id").exists()
    assert (task_dir / "agent-chat-id").read_text().strip() == "my-chat-id-456"
    rules_file = task_dir / ".cursor" / "rules" / "git-workspace.mdc"
    assert rules_file.exists()
    assert "workspace root is not a git project" in rules_file.read_text()
    assert "one level deeper" in rules_file.read_text()

    all_cmds = [call.args[0] for call in mock_popen.call_args_list]
    assert sum(1 for c in all_cmds if c[0] == "cursor") == 1
    assert sum(1 for c in all_cmds if c[0] == "git" and c[1] == "clone") == 1
    assert sum(1 for c in all_cmds if c[0] == "git" and c[1] == "checkout") == 1


@patch("dev_sdk.task_manager.subprocess.Popen")
def test_start_task_no_repo_skips_clone_and_git_workspace_rule(
    mock_popen: MagicMock,
    manager: TaskManager,
    tmp_tasks_root: Path,
) -> None:
    mock_popen.side_effect = _popen_factory(
        {("cursor", "create-chat"): _FakeProc(stdout_lines=["ops-chat\n"])}
    )

    manager.start_task(
        title="Ops",
        task_name="ops-task",
        comment=None,
        repo_url=None,
    )

    task_dir = tmp_tasks_root / "ops-task"
    assert (task_dir / ".cursor" / "rules" / "task-comms.mdc").exists()
    assert not (task_dir / ".cursor" / "rules" / "git-workspace.mdc").exists()
    all_cmds = [call.args[0] for call in mock_popen.call_args_list]
    assert not any(c[0] == "git" for c in all_cmds)


def test_describe_clone_layout_empty(manager: TaskManager, tmp_tasks_root: Path) -> None:
    task_dir = tmp_tasks_root / "t"
    task_dir.mkdir(parents=True)
    label = manager.describe_clone_layout(task_dir)
    assert label is None


def test_describe_clone_layout_shows_origin(manager: TaskManager, tmp_tasks_root: Path) -> None:
    task_dir = tmp_tasks_root / "t"
    task_dir.mkdir(parents=True)
    repo = task_dir / "myrepo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/example/sample.git"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    label = manager.describe_clone_layout(task_dir)
    assert label and "example/sample" in label


@patch("dev_sdk.task_manager.subprocess.Popen")
def test_start_task_calls_on_progress(
    mock_popen: MagicMock,
    manager: TaskManager,
    tmp_tasks_root: Path,
) -> None:
    mock_popen.side_effect = _popen_factory(_start_task_cases(tmp_tasks_root))

    messages: list[str] = []
    manager.start_task(
        title="My Task",
        task_name="my-task",
        comment="Build the feature.",
        repo_url="https://github.com/user/repo.git",
        on_progress=messages.append,
    )

    assert "Created task directory." in messages
    assert "Comms directory ready." in messages
    assert "Cloning repository…" in messages
    assert "Feature branch created." in messages


@patch("dev_sdk.task_manager.subprocess.Popen")
def test_start_task_creates_directory(
    mock_popen: MagicMock,
    manager: TaskManager,
    tmp_tasks_root: Path,
) -> None:
    mock_popen.side_effect = _popen_factory(
        {
            ("cursor", "create-chat"): _FakeProc(stdout_lines=["chat-123\n"]),
            ("git", "clone"): _FakeProc(
                on_start=lambda: (tmp_tasks_root / "foo" / "y").mkdir(parents=True, exist_ok=True)
            ),
            ("git", "checkout"): _FakeProc(),
        }
    )
    manager.start_task(
        title="Foo",
        task_name="foo",
        comment="Bar",
        repo_url="https://github.com/x/y.git",
    )
    assert (tmp_tasks_root / "foo").is_dir()
    assert (tmp_tasks_root / "foo" / "comms").is_dir()
    assert (tmp_tasks_root / "foo" / "agent-chat-id").exists()


def test_start_task_duplicate_name_raises(manager: TaskManager, tmp_tasks_root: Path) -> None:
    (tmp_tasks_root / "existing").mkdir(parents=True)
    with patch("dev_sdk.task_manager.subprocess.Popen"):
        with pytest.raises(FileExistsError):
            manager.start_task(
                title="Existing",
                task_name="existing",
                comment="Desc",
                repo_url="https://github.com/a/b.git",
            )


@patch("dev_sdk.task_manager.subprocess.Popen")
def test_start_task_cancel_aborts_before_subprocess(
    mock_popen: MagicMock,
    manager: TaskManager,
    tmp_tasks_root: Path,
) -> None:
    """If cancel is already set, no subprocesses run and TaskCancelled is raised."""
    calls: list[list[str]] = []

    def factory(cmd, **kwargs):
        calls.append(cmd)
        return _FakeProc()

    mock_popen.side_effect = factory

    with pytest.raises(TaskCancelled):
        manager.start_task(
            title="Cancelme",
            task_name="cancelme",
            comment=None,
            repo_url="https://github.com/x/y.git",
            cancel_check=lambda: True,
        )
    assert not any(c[0] == "git" for c in calls)


@patch("dev_sdk.task_manager.subprocess.Popen")
def test_agent_chat_no_output_raises(
    mock_popen: MagicMock,
    manager: TaskManager,
) -> None:
    """If agent create-chat emits nothing and exits, raise a clear error."""
    mock_popen.return_value = _FakeProc(stdout_lines=[], returncode=0)

    with pytest.raises(RuntimeError, match="did not produce a chat ID|exited with code"):
        manager._create_agent_chat()


def test_list_tasks_empty(manager: TaskManager) -> None:
    assert manager.list_tasks() == []


def test_list_tasks_returns_sorted_excludes_archive_and_hidden(
    manager: TaskManager, tmp_tasks_root: Path
) -> None:
    tmp_tasks_root.mkdir(parents=True)
    (tmp_tasks_root / "z-task").mkdir()
    (tmp_tasks_root / "a-task").mkdir()
    (tmp_tasks_root / ".archive").mkdir()
    (tmp_tasks_root / ".hidden").mkdir()
    assert manager.list_tasks() == ["a-task", "z-task"]


def test_archive_task(manager: TaskManager, tmp_tasks_root: Path) -> None:
    tmp_tasks_root.mkdir(parents=True)
    task_dir = tmp_tasks_root / "my-task"
    task_dir.mkdir()
    (task_dir / "comms").mkdir()
    (task_dir / "comms" / "001-user.md").write_text("# Task\n\nDesc.")
    dest = manager.archive_task("my-task")
    assert not task_dir.exists()
    assert dest.parent == tmp_tasks_root / ".archive"
    assert dest.name.startswith("my-task-")


def test_archive_task_not_found_raises(manager: TaskManager, tmp_tasks_root: Path) -> None:
    tmp_tasks_root.mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="Task not found"):
        manager.archive_task("nonexistent")


def test_repo_name_from_url_with_git_suffix() -> None:
    assert TaskManager._repo_name_from_url("https://github.com/user/repo.git") == "repo"


def test_repo_name_from_url_without_git_suffix() -> None:
    assert TaskManager._repo_name_from_url("https://github.com/user/repo") == "repo"


def test_parse_archive_name() -> None:
    assert TaskManager.parse_archive_name("my-task-mar-14-a1b2c3") == ("my-task", "mar-14")
    assert TaskManager.parse_archive_name("foo-jan-1-abcdef") == ("foo", "jan-1")
    assert TaskManager.parse_archive_name("no-suffix") == ("no-suffix", "")
    assert TaskManager.parse_archive_name("multi-dash-task-dec-31-fedcba") == (
        "multi-dash-task",
        "dec-31",
    )


def test_list_archived_tasks_empty(manager: TaskManager) -> None:
    assert manager.list_archived_tasks() == []


def test_list_archived_tasks_no_archive_dir(manager: TaskManager, tmp_tasks_root: Path) -> None:
    tmp_tasks_root.mkdir(parents=True)
    assert manager.list_archived_tasks() == []


def test_list_archived_tasks_returns_sorted(manager: TaskManager, tmp_tasks_root: Path) -> None:
    archive_root = tmp_tasks_root / ".archive"
    archive_root.mkdir(parents=True)
    older = archive_root / "z-task-mar-14-aaaaaa"
    newest = archive_root / "a-task-mar-15-bbbbbb"
    middle = archive_root / "m-task-mar-14-cccccc"
    older.mkdir()
    newest.mkdir()
    middle.mkdir()
    os.utime(older, (1000, 1000))
    os.utime(middle, (2000, 2000))
    os.utime(newest, (3000, 3000))
    entries = manager.list_archived_tasks()
    assert len(entries) == 3
    assert entries[0].archived_date == "mar-15"
    assert entries[0].task_name == "a-task"
    assert entries[0].archived_at
    assert entries[0].last_modified_at
    assert entries[1].archived_date == "mar-14"
    assert entries[1].task_name == "m-task"
    assert entries[2].archived_date == "mar-14"
    assert entries[2].task_name == "z-task"


def test_unarchive_task(manager: TaskManager, tmp_tasks_root: Path) -> None:
    tmp_tasks_root.mkdir(parents=True)
    archive_root = tmp_tasks_root / ".archive"
    archive_root.mkdir()
    archived = archive_root / "my-task-mar-14-a1b2c3"
    archived.mkdir()
    (archived / "comms").mkdir()
    dest = manager.unarchive_task("my-task-mar-14-a1b2c3")
    assert dest == tmp_tasks_root / "my-task"
    assert dest.is_dir()
    assert not archived.exists()


def test_unarchive_task_target_exists_raises(manager: TaskManager, tmp_tasks_root: Path) -> None:
    tmp_tasks_root.mkdir(parents=True)
    (tmp_tasks_root / "my-task").mkdir()
    archive_root = tmp_tasks_root / ".archive"
    archive_root.mkdir()
    (archive_root / "my-task-mar-14-a1b2c3").mkdir()
    with pytest.raises(FileExistsError, match="Task already exists"):
        manager.unarchive_task("my-task-mar-14-a1b2c3")


def test_unarchive_task_not_found_raises(manager: TaskManager, tmp_tasks_root: Path) -> None:
    tmp_tasks_root.mkdir(parents=True)
    (tmp_tasks_root / ".archive").mkdir()
    with pytest.raises(FileNotFoundError, match="Archived task not found"):
        manager.unarchive_task("nonexistent-mar-14-abcdef")


def _archive_case_chat(chat_id: str = "new-chat-id-789") -> dict:
    return {("cursor", "create-chat"): _FakeProc(stdout_lines=[f"{chat_id}\n"])}


@patch("dev_sdk.task_manager.subprocess.Popen")
def test_copy_task_from_archive(
    mock_popen: MagicMock,
    manager: TaskManager,
    tmp_tasks_root: Path,
) -> None:
    tmp_tasks_root.mkdir(parents=True)
    archive_root = tmp_tasks_root / ".archive"
    archive_root.mkdir()
    archived = archive_root / "my-task-mar-14-a1b2c3"
    archived.mkdir()
    (archived / "comms").mkdir()
    (archived / "comms" / "index.txt").write_text("001-user.md\n")
    (archived / "comms" / "001-user.md").write_text("# Task\n")
    (archived / ".cursor" / "rules").mkdir(parents=True)
    (archived / ".cursor" / "rules" / "task-comms.mdc").write_text("rule")
    (archived / ".cursor" / "rules" / "git-workspace.mdc").write_text("git rule")
    (archived / ".logs").mkdir()
    (archived / ".logs" / "dev-plan-stream-20260314.log").write_text("log content")
    (archived / "agent-chat-id").write_text("old-chat-id")
    mock_popen.side_effect = _popen_factory(_archive_case_chat())

    dest = manager.copy_task_from_archive("my-task-mar-14-a1b2c3")

    assert dest == tmp_tasks_root / "my-task"
    assert dest.is_dir()
    assert (dest / "comms" / "index.txt").read_text() == "001-user.md\n"
    assert (dest / "comms" / "001-user.md").read_text() == "# Task\n"
    assert (dest / ".cursor" / "rules" / "task-comms.mdc").exists()
    assert (dest / ".cursor" / "rules" / "git-workspace.mdc").exists()
    assert not (dest / ".logs").exists()
    assert (dest / "agent-chat-id").read_text().strip() == "new-chat-id-789"
    assert archived.is_dir()


@patch("dev_sdk.task_manager.subprocess.Popen")
def test_copy_task_from_archive_copies_repo(
    mock_popen: MagicMock,
    manager: TaskManager,
    tmp_tasks_root: Path,
) -> None:
    tmp_tasks_root.mkdir(parents=True)
    archive_root = tmp_tasks_root / ".archive"
    archive_root.mkdir()
    archived = archive_root / "foo-mar-14-abcdef"
    archived.mkdir()
    (archived / "comms").mkdir()
    (archived / "comms" / "index.txt").write_text("")
    repo_dir = archived / "myrepo"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()
    (repo_dir / "README").write_text("repo content")
    mock_popen.side_effect = _popen_factory(_archive_case_chat("chat-id"))

    dest = manager.copy_task_from_archive("foo-mar-14-abcdef")

    assert (dest / "myrepo").is_dir()
    assert (dest / "myrepo" / ".git").is_dir()
    assert (dest / "myrepo" / "README").read_text() == "repo content"


@patch("dev_sdk.task_manager.subprocess.Popen")
def test_copy_task_from_archive_target_exists_raises(
    mock_popen: MagicMock,
    manager: TaskManager,
    tmp_tasks_root: Path,
) -> None:
    tmp_tasks_root.mkdir(parents=True)
    (tmp_tasks_root / "my-task").mkdir()
    archive_root = tmp_tasks_root / ".archive"
    archive_root.mkdir()
    (archive_root / "my-task-mar-14-a1b2c3").mkdir()
    (archive_root / "my-task-mar-14-a1b2c3" / "comms").mkdir()
    (archive_root / "my-task-mar-14-a1b2c3" / "comms" / "index.txt").write_text("")

    with pytest.raises(FileExistsError, match="Task already exists"):
        manager.copy_task_from_archive("my-task-mar-14-a1b2c3")


def test_copy_task_from_archive_not_found_raises(manager: TaskManager, tmp_tasks_root: Path) -> None:
    tmp_tasks_root.mkdir(parents=True)
    (tmp_tasks_root / ".archive").mkdir()
    with pytest.raises(FileNotFoundError, match="Archived task not found"):
        manager.copy_task_from_archive("nonexistent-mar-14-abcdef")


@patch("dev_sdk.task_manager.subprocess.Popen")
def test_copy_task_from_archive_task_name_override(
    mock_popen: MagicMock,
    manager: TaskManager,
    tmp_tasks_root: Path,
) -> None:
    tmp_tasks_root.mkdir(parents=True)
    archive_root = tmp_tasks_root / ".archive"
    archive_root.mkdir()
    archived = archive_root / "original-mar-14-a1b2c3"
    archived.mkdir()
    (archived / "comms").mkdir()
    (archived / "comms" / "index.txt").write_text("")
    mock_popen.side_effect = _popen_factory(_archive_case_chat("chat-id"))

    dest = manager.copy_task_from_archive("original-mar-14-a1b2c3", task_name_override="new-name")

    assert dest == tmp_tasks_root / "new-name"
    assert dest.is_dir()


@patch("dev_sdk.task_manager.subprocess.Popen")
def test_copy_task_from_archive_ops_does_not_add_git_workspace_rule(
    mock_popen: MagicMock,
    manager: TaskManager,
    tmp_tasks_root: Path,
) -> None:
    """Archive with comms + rules but no cloned repo must not get git-workspace.mdc backfilled."""
    tmp_tasks_root.mkdir(parents=True)
    archive_root = tmp_tasks_root / ".archive"
    archive_root.mkdir()
    archived = archive_root / "ops-mar-14-a1b2c3"
    archived.mkdir()
    (archived / "comms").mkdir()
    (archived / "comms" / "index.txt").write_text("")
    (archived / ".cursor" / "rules").mkdir(parents=True)
    (archived / ".cursor" / "rules" / "task-comms.mdc").write_text("comms rule")
    mock_popen.side_effect = _popen_factory(_archive_case_chat("new-chat"))

    dest = manager.copy_task_from_archive("ops-mar-14-a1b2c3")

    assert (dest / ".cursor" / "rules" / "task-comms.mdc").exists()
    assert not (dest / ".cursor" / "rules" / "git-workspace.mdc").exists()


@patch("dev_sdk.task_manager.subprocess.Popen")
def test_copy_task_from_archive_backfills_git_workspace_when_repo_copied(
    mock_popen: MagicMock,
    manager: TaskManager,
    tmp_tasks_root: Path,
) -> None:
    """When archive has a repo but no rules dir, copy still adds git-workspace after clone copy."""
    tmp_tasks_root.mkdir(parents=True)
    archive_root = tmp_tasks_root / ".archive"
    archive_root.mkdir()
    archived = archive_root / "with-repo-mar-14-a1b2c3"
    archived.mkdir()
    (archived / "comms").mkdir()
    (archived / "comms" / "index.txt").write_text("")
    repo_dir = archived / "proj"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()
    mock_popen.side_effect = _popen_factory(_archive_case_chat("cid"))

    dest = manager.copy_task_from_archive("with-repo-mar-14-a1b2c3")

    assert (dest / "proj" / ".git").is_dir()
    assert (dest / ".cursor" / "rules" / "git-workspace.mdc").exists()
    assert (dest / ".cursor" / "rules" / "task-comms.mdc").exists()
