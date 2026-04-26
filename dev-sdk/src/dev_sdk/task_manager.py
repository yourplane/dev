"""Task directory and agent setup logic."""

from __future__ import annotations

import logging
import re
import secrets
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable, NamedTuple

from dev_sdk.comms import add_comms, comms_dir


class ArchivedTaskEntry(NamedTuple):
    """A single entry in the archive listing."""

    archived_name: str
    task_name: str
    archived_date: str
    archived_at: str
    last_modified_at: str

logger = logging.getLogger("dev_sdk")

ProgressCallback = Callable[[str], None]

# Archive dir name suffix: -<month>-<day>-<6 hex chars>, e.g. -mar-14-a1b2c3
_ARCHIVE_SUFFIX_RE = re.compile(r"-[a-z]{3}-\d{1,2}-[a-f0-9]{6}$")


class TaskManager:
    """Creates task directories, comms dir, agent chats, and clones repos."""

    def __init__(self, tasks_root: Path) -> None:
        self.tasks_root = Path(tasks_root)

    def start_task(
        self,
        title: str,
        task_name: str,
        comment: str | None,
        repo_url: str,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        """Create task dir, comms dir (and optional first user comment), agent chat, and clone repo."""
        logger.debug(
            "start_task: task_name=%s repo_url=%s task_dir=%s",
            task_name,
            repo_url,
            self.tasks_root / task_name,
        )
        task_dir = self.tasks_root / task_name
        task_dir.mkdir(parents=True, exist_ok=False)
        if on_progress:
            on_progress("Created task directory.")

        self._ensure_comms_dir(task_dir)
        if on_progress:
            on_progress("Comms directory ready.")
        if comment and comment.strip():
            add_comms(task_dir, "user", f"# {title}\n\n{comment.strip()}")
            if on_progress:
                on_progress("Added initial comment to comms.")

        if on_progress:
            on_progress("Creating agent chat…")
        chat_id = self._create_agent_chat()
        if on_progress:
            on_progress("Agent chat created.")
        self._write_chat_id_file(task_dir, chat_id)
        self._write_cursor_rules(task_dir)
        if on_progress:
            on_progress("Cloning repository…")
        self._clone_repo(task_dir, repo_url)
        if on_progress:
            on_progress("Repository cloned.")
        self._checkout_feature_branch(task_dir, repo_url, task_name, on_progress=on_progress)
        logger.debug("start_task: completed task_name=%s", task_name)

    def _ensure_comms_dir(self, task_dir: Path) -> None:
        """Create comms directory and write Cursor rule for comms context."""
        cdir = comms_dir(task_dir)
        cdir.mkdir(parents=True, exist_ok=True)
        rules_dir = task_dir / ".cursor" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        path = rules_dir / "task-comms.mdc"
        path.write_text(
            "---\n"
            "description: Task context in comms directory\n"
            "alwaysApply: true\n"
            "---\n\n"
            "# Task context (comms)\n\n"
            "Look at the `comms` directory in this workspace for task context. "
            "Read the files listed in `comms/index.txt` in order to understand the task "
            "and prior discussion. Add agent comms (e.g. plans, implementation notes) by "
            "creating files in `comms` and appending their filenames to `comms/index.txt`. "
            "Exception: when running in ask/read-only mode (e.g. `dev plan-implement`), do not write to "
            "comms; the dev CLI will add the plan entry.\n",
            encoding="utf-8",
        )

    def _create_agent_chat(self) -> str:
        cmd = ["cursor", "agent", "create-chat"]
        logger.debug("Creating agent chat: cmd=%s", cmd)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )
            chat_id = self._parse_chat_id(result.stdout.strip())
            logger.debug("Agent chat created: chat_id=%s", chat_id)
            return chat_id
        except (subprocess.CalledProcessError, ValueError) as e:
            logger.warning("Agent chat failed: %s", e)
            raise

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
        logger.debug("Cloning repo: repo_url=%s cwd=%s", repo_url, task_dir)
        try:
            subprocess.run(
                ["git", "clone", repo_url],
                cwd=task_dir,
                check=True,
                capture_output=True,
            )
            logger.debug("Repo cloned: repo_url=%s", repo_url)
        except subprocess.CalledProcessError as e:
            logger.warning("Clone failed: %s", e)
            raise

    def _checkout_feature_branch(
        self,
        task_dir: Path,
        repo_url: str,
        task_name: str,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        """Create and checkout a feature branch in the cloned repo (branch name: task/<task_name>)."""
        repo_name = self._repo_name_from_url(repo_url)
        repo_path = task_dir / repo_name
        branch_name = f"task/{task_name}"
        logger.debug("Checking out feature branch: branch=%s cwd=%s", branch_name, repo_path)
        if on_progress:
            on_progress("Checking out feature branch…")
        try:
            subprocess.run(
                ["git", "checkout", "-b", branch_name],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            logger.debug("Feature branch created: branch=%s", branch_name)
        except subprocess.CalledProcessError as e:
            logger.warning("Checkout failed: %s", e)
            raise
        if on_progress:
            on_progress("Feature branch created.")

    @staticmethod
    def _repo_name_from_url(repo_url: str) -> str:
        """Derive repo directory name from URL (e.g. .../repo.git -> repo)."""
        name = repo_url.rstrip("/").split("/")[-1]
        return name.removesuffix(".git") if name.endswith(".git") else name or "repo"

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

    @staticmethod
    def parse_archive_name(archived_name: str) -> tuple[str, str]:
        """Parse archive dir name into (task_name, archived_date). Date is '' if suffix not recognized."""
        m = _ARCHIVE_SUFFIX_RE.search(archived_name)
        if not m:
            return (archived_name, "")
        suffix = m.group(0)
        task_name = archived_name[: -len(suffix)]
        # suffix is like -mar-14-a1b2c3; date part is -mar-14
        date_part = suffix[: -7]  # strip -a1b2c3
        archived_date = date_part.lstrip("-")  # mar-14
        return (task_name, archived_date)

    def list_archived_tasks(self) -> list[ArchivedTaskEntry]:
        """List directories in .archive sorted by most recently archived first."""
        archive_root = self.tasks_root / ".archive"
        if not archive_root.is_dir():
            return []
        entries: list[ArchivedTaskEntry] = []
        for p in archive_root.iterdir():
            if p.is_dir() and not p.name.startswith("."):
                task_name, archived_date = self.parse_archive_name(p.name)
                archived_at, last_modified_at = self._archive_timestamps(p)
                entries.append(
                    ArchivedTaskEntry(
                        archived_name=p.name,
                        task_name=task_name,
                        archived_date=archived_date,
                        archived_at=archived_at,
                        last_modified_at=last_modified_at,
                    )
                )
        entries.sort(
            key=lambda e: (
                e.archived_at,
                e.last_modified_at,
                e.archived_name,
            ),
            reverse=True,
        )
        return entries

    @staticmethod
    def _format_timestamp(ts: float) -> str:
        """Format a filesystem timestamp as local ISO-8601."""
        return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")

    def _archive_timestamps(self, archive_dir: Path) -> tuple[str, str]:
        """Return (archived_at, last_modified_at) for an archive directory."""
        dir_stat = archive_dir.stat()
        archived_at_ts = dir_stat.st_mtime
        newest_modified_ts = archived_at_ts
        for child in archive_dir.rglob("*"):
            try:
                child_mtime = child.stat().st_mtime
            except OSError:
                continue
            if child_mtime > newest_modified_ts:
                newest_modified_ts = child_mtime
        return (
            self._format_timestamp(archived_at_ts),
            self._format_timestamp(newest_modified_ts),
        )

    def unarchive_task(self, archived_name: str) -> Path:
        """Move .archive/<archived_name> back to tasks_root/<task_name>, stripping -date-random suffix."""
        archived_name = archived_name.strip("/")
        if not archived_name or ".." in archived_name or "/" in archived_name or "\\" in archived_name:
            raise FileNotFoundError(f"Invalid archive name: {archived_name}")
        archive_root = self.tasks_root / ".archive"
        src = (archive_root / archived_name).resolve()
        if not src.is_dir() or src.parent != archive_root.resolve():
            raise FileNotFoundError(f"Archived task not found: {archived_name}")
        task_name, _ = self.parse_archive_name(archived_name)
        if not task_name:
            raise FileNotFoundError(f"Invalid archive name: {archived_name}")
        dest = self.tasks_root / task_name
        if dest.exists():
            raise FileExistsError(f"Task already exists: {task_name}")
        shutil.move(str(src), str(dest))
        return dest

    def copy_task_from_archive(
        self,
        archived_name: str,
        task_name_override: str | None = None,
    ) -> Path:
        """Create a new task from an archived task: same name and comms, new agent chat, no logs.
        Copies comms/, .cursor/rules/, and any cloned repo dirs. Does not copy .logs/ or agent-chat-id.
        """
        archived_name = archived_name.strip("/")
        if not archived_name or ".." in archived_name or "/" in archived_name or "\\" in archived_name:
            raise FileNotFoundError(f"Invalid archive name: {archived_name}")
        archive_root = self.tasks_root / ".archive"
        src = (archive_root / archived_name).resolve()
        if not src.is_dir() or src.parent != archive_root.resolve():
            raise FileNotFoundError(f"Archived task not found: {archived_name}")
        task_name, _ = self.parse_archive_name(archived_name)
        if task_name_override is not None and task_name_override.strip():
            task_name = task_name_override.strip()
        if not task_name:
            raise FileNotFoundError(f"Invalid archive name: {archived_name}")
        dest = self.tasks_root / task_name
        if dest.exists():
            raise FileExistsError(f"Task already exists: {task_name}")
        dest.mkdir(parents=True)
        # Copy comms (entire dir)
        src_comms = src / "comms"
        if src_comms.is_dir():
            shutil.copytree(src_comms, dest / "comms")
        # Copy .cursor/rules
        src_rules = src / ".cursor" / "rules"
        if src_rules.is_dir():
            (dest / ".cursor").mkdir(parents=True, exist_ok=True)
            shutil.copytree(src_rules, dest / ".cursor" / "rules")
        else:
            self._write_cursor_rules(dest)
            self._ensure_comms_dir(dest)
        # Copy any cloned repo dirs (directories containing .git, excluding comms and .cursor)
        for p in src.iterdir():
            if (
                p.is_dir()
                and not p.name.startswith(".")
                and p.name not in ("comms", ".cursor")
                and (p / ".git").is_dir()
            ):
                shutil.copytree(p, dest / p.name)
        # New agent chat for the new task
        chat_id = self._create_agent_chat()
        self._write_chat_id_file(dest, chat_id)
        # Ensure cursor rules exist if we only had partial copy
        if not (dest / ".cursor" / "rules" / "git-workspace.mdc").exists():
            self._write_cursor_rules(dest)
        if not (dest / ".cursor" / "rules" / "task-comms.mdc").exists():
            self._ensure_comms_dir(dest)
        logger.debug("copy_task_from_archive: completed task_name=%s", task_name)
        return dest
