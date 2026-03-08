"""Comms directory: ordered list of user/agent comms files at task root."""

from pathlib import Path

COMMS_DIR = "comms"
INDEX_FILE = "index.txt"


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
