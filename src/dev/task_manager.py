"""Task directory and agent setup logic."""

from __future__ import annotations

import secrets
import shutil
import subprocess
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
        self._clone_repo(task_dir, repo_url)

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

    def _clone_repo(self, task_dir: Path, repo_url: str) -> None:
        """Clone repo into task_dir; git uses the repo name from the URL as the directory."""
        subprocess.run(
            ["git", "clone", repo_url],
            cwd=task_dir,
            check=True,
            capture_output=True,
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
