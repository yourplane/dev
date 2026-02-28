"""Task directory and agent setup logic."""

from __future__ import annotations

import secrets
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


class TaskManager:
    """Creates task directories, task files, agent chats, and clones repos."""

    def __init__(self, tasks_root: Path) -> None:
        self.tasks_root = Path(tasks_root)

    def start_task(
        self,
        title: str,
        task_name: str,
        description: str,
        repo_url: str,
        agent_cmd: str = "cursor",
        agent_create_chat_args: list[str] | None = None,
    ) -> None:
        """Create task dir, task file, agent chat + launch script, and clone repo."""
        agent_create_chat_args = agent_create_chat_args or ["agent", "create-chat"]
        task_dir = self.tasks_root / task_name
        task_dir.mkdir(parents=True, exist_ok=False)

        self._write_task_file(task_dir, title, description)
        chat_id = self._create_agent_chat(agent_cmd, agent_create_chat_args)
        self._write_chat_id_file(task_dir, chat_id)
        self._write_cursor_rules(task_dir)
        self._clone_repo(task_dir, repo_url)
        self._setup_pyenv(task_dir, repo_url)

    def _write_task_file(self, task_dir: Path, title: str, description: str) -> None:
        path = task_dir / "task.md"
        path.write_text(f"# {title}\n\n{description}\n", encoding="utf-8")

    def _create_agent_chat(
        self, agent_cmd: str, agent_create_chat_args: list[str]
    ) -> str:
        cmd = [agent_cmd] + agent_create_chat_args
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        return self._parse_chat_id(result.stdout.strip())

    def _parse_chat_id(self, output: str) -> str:
        """Extract chat ID from agent create-chat output (e.g. UUID or last line)."""
        lines = [s.strip() for s in output.splitlines() if s.strip()]
        if not lines:
            raise ValueError("No output from agent create-chat")
        last = lines[-1]
        if not last:
            raise ValueError("Could not parse chat ID from agent output")
        return last

    def _write_chat_id_file(self, task_dir: Path, chat_id: str) -> None:
        """Write the agent chat ID to a file in the task directory."""
        path = task_dir / "agent-chat-id"
        path.write_text(chat_id.strip(), encoding="utf-8")

    def _write_cursor_rules(self, task_dir: Path) -> None:
        """Write .cursor/rules/ so the agent knows the workspace root is not a git repo."""
        rules_dir = task_dir / ".cursor" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        path = rules_dir / "git-workspace.mdc"
        path.write_text(
            "---\n"
            "description: Git project location in the task workspace\n"
            "alwaysApply: true\n"
            "---\n\n"
            "# Git project location\n\n"
            "The workspace root is not a git project. Git projects are one level deeper "
            "(each subdirectory that was cloned from a repo is its own git project).\n",
            encoding="utf-8",
        )

    def _clone_repo(self, task_dir: Path, repo_url: str) -> None:
        """Clone repo into task_dir; git uses the repo name from the URL as the directory."""
        subprocess.run(
            ["git", "clone", repo_url],
            cwd=task_dir,
            check=True,
            capture_output=True,
        )

    @staticmethod
    def _repo_name_from_url(repo_url: str) -> str:
        """Derive repo directory name from URL (e.g. .../repo.git -> repo)."""
        name = repo_url.rstrip("/").split("/")[-1]
        return name.removesuffix(".git") if name.endswith(".git") else name or "repo"

    def _setup_pyenv(self, task_dir: Path, repo_url: str) -> None:
        """Create a venv, install the cloned repo in editable mode, and add a Cursor rule for testing."""
        repo_name = self._repo_name_from_url(repo_url)
        repo_path = task_dir / repo_name

        if not (repo_path / "pyproject.toml").exists() and not (
            repo_path / "setup.py"
        ).exists():
            print(
                f"Warning: {repo_name} has no pyproject.toml or setup.py; skipping Python venv setup.",
                file=sys.stderr,
            )
            return

        venv_name = task_dir.name
        venv_dir = task_dir / venv_name
        try:
            subprocess.run(
                [sys.executable, "-m", "venv", str(venv_dir)],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            print(
                f"Warning: failed to create virtual environment: {e}",
                file=sys.stderr,
            )
            return

        pip = venv_dir / "bin" / "pip"
        if sys.platform == "win32":
            pip = venv_dir / "Scripts" / "pip.exe"
        try:
            subprocess.run(
                [str(pip), "install", "-e", str(repo_path)],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            print(
                f"Warning: failed to install {repo_name} in editable mode: {e}",
                file=sys.stderr,
            )
            return

        rules_dir = task_dir / ".cursor" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        rule_path = rules_dir / "pyenv-testing.mdc"
        rule_path.write_text(
            "---\n"
            "description: Use the task virtual environment for testing\n"
            "alwaysApply: true\n"
            "---\n\n"
            "# Testing with the task virtual environment\n\n"
            "When running or testing the cloned repo (e.g. its CLI or tests), use the tool "
            "installed in this task's virtual environment:\n\n"
            f"- **Virtual environment path:** `{venv_name}` at the task root\n"
            f"- **Run the installed CLI:** `{venv_name}/bin/<command>` (or `Scripts\\<command>.exe` on Windows)\n"
            f"- **Run tests:** Use `{venv_name}/bin/python -m pytest` or `{venv_name}/bin/tox` so that the "
            "editable-installed package and its dependencies are used.\n\n"
            f"Do not rely on a system-wide or other Python environment for testing; always "
            f"invoke via this task's `{venv_name}` to ensure the correct editable installation is under test.\n",
            encoding="utf-8",
        )

    def list_tasks(self) -> list[str]:
        """Return sorted list of task directory names (excludes .archive and hidden dirs)."""
        root = Path(self.tasks_root)
        if not root.exists():
            return []
        return sorted(
            p.name
            for p in root.iterdir()
            if p.is_dir() and not p.name.startswith(".") and p.name != ".archive"
        )

    def archive_task(self, task_name: str) -> Path:
        """Move task directory to .archive with name task_name-<date>-<random>. Returns archive path."""
        task_name = task_name.strip("/")
        task_dir = self.tasks_root / task_name
        if not task_dir.exists() or not task_dir.is_dir():
            raise FileNotFoundError(f"Task not found: {task_name}")
        archive_root = self.tasks_root / ".archive"
        archive_root.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%b-%d").lower()
        random_suffix = secrets.token_hex(3)
        dest_name = f"{task_name}-{date_str}-{random_suffix}"
        dest = archive_root / dest_name
        shutil.move(str(task_dir), str(dest))
        return dest
