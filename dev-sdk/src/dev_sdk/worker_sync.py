"""Local worker sync state: outbox, stream tailing metadata, origin-based comms sync."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from dev_sdk.comms import LOGS_DIR, comms_dir, index_path, read_index

CLOUD_DIR = ".cloud"
OUTBOX_FILE = "outbox.json"
STREAMS_FILE = "streams.json"
TAIL_STATE_FILE = "tail_state.json"
PROGRESS_FILE = "progress.jsonl"


class SyncPushClient(Protocol):
    def sync_push(self, task_name: str, items: list[dict]) -> list[dict]: ...


def cloud_dir(task_dir: Path) -> Path:
    return task_dir / CLOUD_DIR


@dataclass
class OutboxEntry:
    error: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    sync_failures: int = 0
    unhealthy: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OutboxEntry:
        return cls(
            error=data.get("error"),
            result=dict(data.get("result") or {}),
            sync_failures=int(data.get("sync_failures") or 0),
            unhealthy=bool(data.get("unhealthy")),
        )


def outbox_path(task_dir: Path) -> Path:
    return cloud_dir(task_dir) / OUTBOX_FILE


def has_outbox(task_dir: Path) -> bool:
    return outbox_path(task_dir).is_file()


def read_outbox(task_dir: Path) -> OutboxEntry | None:
    path = outbox_path(task_dir)
    if not path.is_file():
        return None
    return OutboxEntry.from_dict(json.loads(path.read_text(encoding="utf-8")))


def write_outbox(task_dir: Path, entry: OutboxEntry) -> None:
    path = outbox_path(task_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(entry), indent=2) + "\n", encoding="utf-8")


def clear_outbox(task_dir: Path) -> None:
    path = outbox_path(task_dir)
    if path.is_file():
        path.unlink()


@dataclass
class StreamsState:
    active_log: str | None = None
    active_bash: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StreamsState:
        return cls(
            active_log=data.get("active_log"),
            active_bash=data.get("active_bash"),
        )


def streams_path(task_dir: Path) -> Path:
    return cloud_dir(task_dir) / STREAMS_FILE


def read_streams(task_dir: Path) -> StreamsState:
    path = streams_path(task_dir)
    if not path.is_file():
        return StreamsState()
    return StreamsState.from_dict(json.loads(path.read_text(encoding="utf-8")))


def write_streams(task_dir: Path, state: StreamsState) -> None:
    path = streams_path(task_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2) + "\n", encoding="utf-8")


def clear_streams(task_dir: Path) -> None:
    path = streams_path(task_dir)
    if path.is_file():
        path.unlink()


@dataclass
class TailState:
    log_filename: str | None = None
    log_offset: int = 0
    bash_filename: str | None = None
    bash_offset: int = 0
    progress_offset: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TailState:
        return cls(
            log_filename=data.get("log_filename"),
            log_offset=int(data.get("log_offset") or 0),
            bash_filename=data.get("bash_filename"),
            bash_offset=int(data.get("bash_offset") or 0),
            progress_offset=int(data.get("progress_offset") or 0),
        )


def tail_state_path(task_dir: Path) -> Path:
    return cloud_dir(task_dir) / TAIL_STATE_FILE


def read_tail_state(task_dir: Path) -> TailState:
    path = tail_state_path(task_dir)
    if not path.is_file():
        return TailState()
    return TailState.from_dict(json.loads(path.read_text(encoding="utf-8")))


def write_tail_state(task_dir: Path, state: TailState) -> None:
    path = tail_state_path(task_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2) + "\n", encoding="utf-8")


def append_progress(task_dir: Path, message: str) -> None:
    path = cloud_dir(task_dir) / PROGRESS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"message": message}) + "\n")


def _is_comms_data_file(name: str) -> bool:
    if name == "index.txt":
        return False
    return name.endswith(".md") or (name.endswith(".sh") and "-run-plan" in name)


def scan_local_comms_filenames(task_dir: Path) -> list[str]:
    cdir = comms_dir(task_dir)
    if not cdir.is_dir():
        return []
    names = sorted(p.name for p in cdir.iterdir() if p.is_file() and _is_comms_data_file(p.name))
    return names


def repair_local_index(task_dir: Path) -> list[str]:
    """Ensure index.txt lists every local comms file (fixes orphan files)."""
    local = scan_local_comms_filenames(task_dir)
    indexed = read_index(task_dir)
    seen = set(indexed)
    merged = list(indexed)
    for name in local:
        if name not in seen:
            merged.append(name)
            seen.add(name)
    if merged != indexed:
        idx = index_path(task_dir)
        idx.parent.mkdir(parents=True, exist_ok=True)
        idx.write_text("\n".join(merged) + ("\n" if merged else ""), encoding="utf-8")
    return merged


def merge_index_after_pull(local_files: set[str], cloud_index: list[str]) -> list[str]:
    """Merge cloud index with local-only files (preserve cloud order, append locals)."""
    seen: set[str] = set()
    merged: list[str] = []
    for name in cloud_index:
        if name in local_files and name not in seen:
            merged.append(name)
            seen.add(name)
    for name in sorted(local_files):
        if name not in seen:
            merged.append(name)
            seen.add(name)
    return merged


def collect_comms_push_items(task_dir: Path) -> list[dict]:
    repair_local_index(task_dir)
    cdir = comms_dir(task_dir)
    push: list[dict] = []
    for filename in repair_local_index(task_dir):
        fp = cdir / filename
        if fp.is_file():
            push.append(
                {
                    "filename": filename,
                    "content": fp.read_text(encoding="utf-8", errors="replace"),
                    "origin": "worker",
                    "created_at": fp.stat().st_mtime,
                    "deletable": None,
                }
            )
    idx = index_path(task_dir)
    if idx.is_file():
        push.append(
            {
                "filename": "index.txt",
                "content": idx.read_text(encoding="utf-8", errors="replace"),
                "origin": "worker",
                "created_at": idx.stat().st_mtime,
                "deletable": None,
            }
        )
    return push


def apply_comms_pull(task_dir: Path, pull: list[dict]) -> None:
    cdir = comms_dir(task_dir)
    cdir.mkdir(parents=True, exist_ok=True)
    cloud_index: list[str] | None = None
    cloud_index_content: str | None = None
    for item in pull:
        filename = item.get("filename")
        content = item.get("content")
        origin = item.get("origin", "cloud")
        if not filename or content is None:
            continue
        if filename == "index.txt" and origin == "cloud":
            cloud_index = [
                line.strip()
                for line in str(content).splitlines()
                if line.strip()
            ]
            cloud_index_content = str(content)
            continue
        if origin == "cloud":
            fp = cdir / filename
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(str(content), encoding="utf-8")

    local_files = set(scan_local_comms_filenames(task_dir))
    if cloud_index is not None:
        merged = merge_index_after_pull(local_files, cloud_index)
        index_path(task_dir).write_text(
            "\n".join(merged) + ("\n" if merged else ""),
            encoding="utf-8",
        )
    elif cloud_index_content is not None:
        index_path(task_dir).write_text(cloud_index_content, encoding="utf-8")


def sync_task_comms_origin(client: SyncPushClient, task_dir: Path, task_name: str) -> None:
    if not task_dir.is_dir():
        return
    push = collect_comms_push_items(task_dir)
    pull = client.sync_push(task_name, push)
    non_index = [item for item in pull if item.get("filename") != "index.txt"]
    index_items = [item for item in pull if item.get("filename") == "index.txt"]
    apply_comms_pull(task_dir, non_index + index_items)


class LogUploadClient(Protocol):
    def upload_log_chunk(
        self,
        task_name: str,
        filename: str,
        chunk: bytes,
        *,
        kind: str = "log",
    ) -> None: ...


def _read_file_from_offset(path: Path, offset: int) -> tuple[bytes, int]:
    if not path.is_file():
        return b"", offset
    size = path.stat().st_size
    if size <= offset:
        return b"", size
    with path.open("rb") as f:
        f.seek(offset)
        return f.read(), size


def tail_log_file(
    client: LogUploadClient,
    task_dir: Path,
    task_name: str,
    filename: str,
    state: TailState,
) -> TailState:
    log_path = task_dir / LOGS_DIR / filename
    if not log_path.is_file():
        return state
    if state.log_filename != filename:
        state.log_filename = filename
        state.log_offset = 0
        client.upload_log_chunk(task_name, filename, b"")
    chunk, total = _read_file_from_offset(log_path, state.log_offset)
    if chunk:
        client.upload_log_chunk(task_name, filename, chunk)
        state.log_offset = total
    write_tail_state(task_dir, state)
    return state


def tail_bash_file(
    client: LogUploadClient,
    task_dir: Path,
    task_name: str,
    filename: str,
    state: TailState,
) -> TailState:
    bash_path = comms_dir(task_dir) / filename
    if not bash_path.is_file():
        return state
    if state.bash_filename != filename:
        state.bash_filename = filename
        state.bash_offset = 0
        client.upload_log_chunk(task_name, filename, b"", kind="bash")
    chunk, total = _read_file_from_offset(bash_path, state.bash_offset)
    if chunk:
        client.upload_log_chunk(
            task_name,
            filename,
            chunk,
            kind="bash",
        )
        state.bash_offset = total
    write_tail_state(task_dir, state)
    return state


def tail_streams(
    client: LogUploadClient,
    task_dir: Path,
    task_name: str,
    streams: StreamsState,
    state: TailState,
) -> TailState:
    logs_dir = task_dir / LOGS_DIR

    log_name = streams.active_log
    if log_name:
        state = tail_log_file(client, task_dir, task_name, log_name, state)

    bash_name = streams.active_bash
    if bash_name:
        state = tail_bash_file(client, task_dir, task_name, bash_name, state)

    return state


class ProgressClient(Protocol):
    def progress(self, task_name: str, message: str) -> None: ...


def forward_progress(
    client: ProgressClient,
    task_dir: Path,
    task_name: str,
    state: TailState,
) -> TailState:
    path = cloud_dir(task_dir) / PROGRESS_FILE
    if not path.is_file():
        return state
    data = path.read_bytes()
    if len(data) <= state.progress_offset:
        return state
    new_bytes = data[state.progress_offset :]
    state.progress_offset = len(data)
    for line in new_bytes.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = obj.get("message")
        if isinstance(msg, str) and msg.strip():
            client.progress(task_name, msg.strip())
    write_tail_state(task_dir, state)
    return state
