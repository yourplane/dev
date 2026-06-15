"""Comms directory: ordered list of user/agent comms files at task root."""

import json
from pathlib import Path

COMMS_DIR = "comms"
INDEX_FILE = "index.txt"
LOGS_DIR = ".logs"


def comms_dir(task_dir: Path) -> Path:
    """Return path to comms directory (task_dir/comms)."""
    return task_dir / COMMS_DIR


def index_path(task_dir: Path) -> Path:
    """Return path to comms index file."""
    return comms_dir(task_dir) / INDEX_FILE


def _next_sequence(task_dir: Path) -> int:
    """Return next 1-based sequence number from existing comms filenames."""
    cdir = comms_dir(task_dir)
    if not cdir.exists():
        return 1
    max_n = 0
    for p in cdir.iterdir():
        if p.is_file() and p.name != INDEX_FILE:
            if p.suffix == ".md" or (p.suffix == ".sh" and "-run-plan" in p.stem):
                try:
                    n = int(p.name.split("-")[0])
                    if n > max_n:
                        max_n = n
                except ValueError:
                    pass
    return max_n + 1


def next_sequence(task_dir: Path) -> int:
    """Return next 1-based sequence number for a new comms file (plan or script)."""
    return _next_sequence(task_dir)


BASH_COMMS_INPUT_START_LINE = "__DEV_BASH_INPUT__"
BASH_COMMS_INPUT_END_LINE = "__DEV_BASH_INPUT_END__"


def bash_comms_input_header(shell_command: str) -> str:
    """
    UTF-8 prefix for *-user-bash.md: wraps the shell command so multi-line input is
    distinct from streamed stdout (history/UI parse everything between delimiters).
    """
    return (
        f"{BASH_COMMS_INPUT_START_LINE}\n"
        f"{shell_command}\n"
        f"{BASH_COMMS_INPUT_END_LINE}\n"
    )


def begin_streaming_bash_comms(task_dir: Path, shell_command: str) -> Path:
    """
    Create a new indexed comms file NNN-user-bash.md with a delimiter-wrapped command header.
    Caller appends stdout (binary) then a UTF-8 footer with --- and exit metadata.
    """
    cdir = comms_dir(task_dir)
    cdir.mkdir(parents=True, exist_ok=True)
    seq = _next_sequence(task_dir)
    filename = f"{seq:03d}-user-bash.md"
    path = cdir / filename
    path.write_text(bash_comms_input_header(shell_command), encoding="utf-8")
    idx = index_path(task_dir)
    with open(idx, "a", encoding="utf-8") as f:
        f.write(filename + "\n")
    return path


def add_comms(
    task_dir: Path,
    role: str,
    content: str,
    *,
    kind: str | None = None,
) -> Path:
    """
    Append a comms file to the comms dir and index.
    role: 'user' or 'agent'
    kind: optional subtype, e.g. 'plan' for agent (filename like 002-agent-plan.md).
    Returns path to the written file.
    """
    cdir = comms_dir(task_dir)
    cdir.mkdir(parents=True, exist_ok=True)
    seq = _next_sequence(task_dir)
    if kind:
        filename = f"{seq:03d}-{role}-{kind}.md"
    else:
        filename = f"{seq:03d}-{role}.md"
    path = cdir / filename
    path.write_text(content.strip() + "\n", encoding="utf-8")
    idx = index_path(task_dir)
    with open(idx, "a", encoding="utf-8") as f:
        f.write(filename + "\n")
    return path


def read_index(task_dir: Path) -> list[str]:
    """Return ordered list of comms filenames from index. Empty if no index."""
    idx = index_path(task_dir)
    if not idx.exists():
        return []
    return [line.strip() for line in idx.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_comms_content(task_dir: Path) -> str:
    """Read all comms in order and return concatenated content (for agent context)."""
    cdir = comms_dir(task_dir)
    if not cdir.exists():
        return ""
    order = read_index(task_dir)
    parts = []
    for name in order:
        p = cdir / name
        if p.exists():
            parts.append(p.read_text(encoding="utf-8").strip())
    return "\n\n---\n\n".join(parts) if parts else ""


def has_agent_logs(task_dir: Path) -> bool:
    """Return True if the task has at least one agent log file in .logs/."""
    logs_dir = task_dir / LOGS_DIR
    if not logs_dir.is_dir():
        return False
    return any(p.is_file() and p.suffix == ".log" for p in logs_dir.iterdir())


def _comms_file_created_epoch_secs(path: Path) -> float:
    """Same ordering key as feed: birthtime when available, else mtime."""
    try:
        st = path.stat()
        if hasattr(st, "st_birthtime") and st.st_birthtime:
            return float(st.st_birthtime)
        return float(st.st_mtime)
    except OSError:
        return 0.0


def _log_end_epoch_secs(log_path: Path) -> float:
    """
    Approximate end time of an agent JSONL log: timestamp_ms on the last parseable JSON line,
    else max timestamp_ms in the file, else the log file's birthtime/mtime (same as feed).
    """
    try:
        text = log_path.read_text(encoding="utf-8")
    except OSError:
        return 0.0
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return _comms_file_created_epoch_secs(log_path)

    last_obj: dict | None = None
    for line in reversed(lines):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            last_obj = obj
            break
    if last_obj is not None:
        ts = last_obj.get("timestamp_ms")
        if isinstance(ts, (int, float)) and ts > 0:
            return float(ts) / 1000.0

    max_sec: float | None = None
    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            ts = obj.get("timestamp_ms")
            if isinstance(ts, (int, float)) and ts > 0:
                sec = float(ts) / 1000.0
                if max_sec is None or sec > max_sec:
                    max_sec = sec
    if max_sec is not None:
        return max_sec
    return _comms_file_created_epoch_secs(log_path)


def agent_logs_cutoff_epoch_secs(task_dir: Path) -> float | None:
    """Latest log-end time among .logs/*.log, or None if there are no log files."""
    logs_dir = task_dir / LOGS_DIR
    if not logs_dir.is_dir():
        return None
    log_files = [p for p in logs_dir.iterdir() if p.is_file() and p.suffix == ".log"]
    if not log_files:
        return None
    return max(_log_end_epoch_secs(p) for p in log_files)


def comms_file_removable_at_cutoff(comm_path: Path, logs_cutoff: float | None) -> bool:
    """True if comm_path may be removed given a pre-computed agent-logs cutoff."""
    if logs_cutoff is None:
        return True
    if not comm_path.is_file():
        return True
    return _comms_file_created_epoch_secs(comm_path) > logs_cutoff


def comms_file_removable(task_dir: Path, comm_path: Path) -> bool:
    """True if an existing comms file at comm_path may be removed (same rules as remove_comms)."""
    return comms_file_removable_at_cutoff(comm_path, agent_logs_cutoff_epoch_secs(task_dir))


def remove_comms(task_dir: Path, filename: str) -> None:
    """Remove a comms file and its index entry.

    When agent logs exist, removal is allowed only if the comm file is strictly newer than the
    end of the last agent log event (JSONL timestamp_ms), per task policy.
    """
    if not filename or "/" in filename or "\\" in filename or filename.strip() in ("", ".", ".."):
        raise ValueError("Invalid filename")
    filename = filename.strip()
    cdir = comms_dir(task_dir)
    path = (cdir / filename).resolve()
    if not path.parent.resolve().samefile(cdir.resolve()):
        raise ValueError("Invalid filename")
    if path.is_file() and not comms_file_removable(task_dir, path):
        raise ValueError(
            "Cannot remove comms that are not strictly after the last agent log event"
        )
    if path.is_file():
        path.unlink()
    idx = index_path(task_dir)
    if idx.exists():
        lines = [line.strip() for line in idx.read_text(encoding="utf-8").splitlines() if line.strip()]
        new_lines = [line for line in lines if line != filename]
        idx.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")
