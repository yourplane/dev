"""Task directory and agent setup logic."""

from __future__ import annotations

import subprocess
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
        self._write_launch_script(task_dir, agent_cmd, chat_id)
        self._clone_repo(task_dir, task_name, repo_url)

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

    def _write_launch_script(
        self, task_dir: Path, agent_cmd: str, chat_id: str
    ) -> None:
        path = task_dir / "launch-agent.sh"
        content = f"""#!/bin/bash
# Launch Cursor agent with chat ID for this task
exec {agent_cmd} agent chat {chat_id}
"""
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def _clone_repo(self, task_dir: Path, task_name: str, repo_url: str) -> None:
        clone_dir = task_dir / task_name
        subprocess.run(
            ["git", "clone", repo_url, str(clone_dir)],
            check=True,
            capture_output=True,
        )
