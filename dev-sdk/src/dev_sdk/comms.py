"""Comms directory: ordered list of user/agent comms files at task root."""

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


def remove_comms(task_dir: Path, filename: str) -> None:
    """Remove a comms file and its index entry. Not allowed when the task has agent logs."""
    if not filename or "/" in filename or "\\" in filename or filename.strip() in ("", ".", ".."):
        raise ValueError("Invalid filename")
    filename = filename.strip()
    if has_agent_logs(task_dir):
        raise ValueError("Cannot remove comms when the task has agent logs")
    cdir = comms_dir(task_dir)
    path = (cdir / filename).resolve()
    if not path.parent.resolve().samefile(cdir.resolve()):
        raise ValueError("Invalid filename")
    if path.is_file():
        path.unlink()
    idx = index_path(task_dir)
    if idx.exists():
        lines = [line.strip() for line in idx.read_text(encoding="utf-8").splitlines() if line.strip()]
        new_lines = [line for line in lines if line != filename]
        idx.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")
