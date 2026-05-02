"""Manage dev-server + dev-frontend daemon instances (background processes, ports, state)."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable
from urllib.error import URLError
from urllib.request import urlopen

# Ranges chosen to avoid typical dev ports (3000, 5173, 8000, 8080, etc.).
BACKEND_PORT_MIN = 28430
BACKEND_PORT_MAX = 28529
FRONTEND_PORT_MIN = 39430
FRONTEND_PORT_MAX = 39529

READY_TIMEOUT_S = 60.0
READY_POLL_S = 0.25


class DaemonError(Exception):
    """Raised when daemon operations fail."""


@dataclass
class DaemonRecord:
    """Persisted state for one daemon instance."""

    id: str
    repo_root: str
    backend_port: int
    frontend_port: int
    backend_pid: int
    frontend_pid: int
    started_at: float
    dev_cli_path: str
    uv_path: str
    npm_path: str
    backend_log: str
    frontend_log: str

    def to_json_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json_dict(cls, data: dict) -> DaemonRecord:
        return cls(
            id=data["id"],
            repo_root=data["repo_root"],
            backend_port=int(data["backend_port"]),
            frontend_port=int(data["frontend_port"]),
            backend_pid=int(data["backend_pid"]),
            frontend_pid=int(data["frontend_pid"]),
            started_at=float(data["started_at"]),
            dev_cli_path=data["dev_cli_path"],
            uv_path=data["uv_path"],
            npm_path=data["npm_path"],
            backend_log=data["backend_log"],
            frontend_log=data["frontend_log"],
        )


def daemon_runtime_root() -> Path:
    base = os.environ.get("XDG_DATA_HOME", "").strip()
    if base:
        root = Path(base) / "dev" / "daemon"
    else:
        root = Path.home() / ".local" / "share" / "dev" / "daemon"
    return root


def instances_dir() -> Path:
    d = daemon_runtime_root() / "instances"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _lock_path() -> Path:
    return daemon_runtime_root() / ".daemon-start.lock"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _bind_check(host: str, port: int) -> bool:
    """Return True if port appears free on host (best-effort)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def port_available(host: str, port: int, *, exclude_daemon_ports: bool = True) -> bool:
    """True if nothing is listening on host:port and port is not reserved by another live daemon."""
    if not _bind_check(host, port):
        return False
    if exclude_daemon_ports and _port_reserved_by_live_daemon(host, port):
        return False
    return True


def _port_reserved_by_live_daemon(host: str, port: int) -> bool:
    if host not in ("127.0.0.1", "localhost"):
        return False
    for rec in iter_daemon_records():
        if not rec.backend_alive() and not rec.frontend_alive():
            continue
        if port in (rec.record.backend_port, rec.record.frontend_port):
            return True
    return False


def pick_port(
    host: str,
    low: int,
    high: int,
    *,
    preferred: int | None = None,
) -> int:
    """Pick first available TCP port in [low, high], or validate preferred."""
    if preferred is not None:
        if low <= preferred <= high and port_available(host, preferred):
            return preferred
        raise DaemonError(
            f"Port {preferred} is not available (must be in {low}-{high} and free)."
        )
    for p in range(low, high + 1):
        if port_available(host, p):
            return p
    raise DaemonError(f"No free port in range {low}-{high} on {host}.")


def validate_repo_root(repo_root: Path) -> Path:
    root = repo_root.expanduser().resolve()
    if not (root / "dev-server").is_dir():
        raise DaemonError(f"Not a dev repo root (missing dev-server): {root}")
    if not (root / "dev-frontend").is_dir():
        raise DaemonError(f"Not a dev repo root (missing dev-frontend): {root}")
    return root


def _resolve_uv() -> str:
    env = os.environ.get("DEV_DAEMON_UV", "").strip()
    if env:
        return env
    path = shutil.which("uv")
    if path:
        return path
    raise DaemonError("uv not found on PATH (set DEV_DAEMON_UV to the full path).")


def _resolve_npm() -> str:
    env = os.environ.get("DEV_DAEMON_NPM", "").strip()
    if env:
        return env
    path = shutil.which("npm")
    if path:
        return path
    raise DaemonError("npm not found on PATH (set DEV_DAEMON_NPM to the full path).")


def _dev_cli_path() -> str:
    # argv[0] is how this CLI was invoked (e.g. `.venv/bin/dev`)
    return os.path.abspath(sys.argv[0]) if sys.argv else sys.executable


def _wait_http_ready(url: str, timeout_s: float = READY_TIMEOUT_S) -> None:
    deadline = time.monotonic() + timeout_s
    last_err: str | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2) as resp:  # noqa: S310 — intentional localhost check
                if resp.status == 200:
                    return
        except URLError as e:
            last_err = str(e.reason if hasattr(e, "reason") else e)
        except OSError as e:
            last_err = str(e)
        time.sleep(READY_POLL_S)
    raise DaemonError(f"Server did not become ready at {url!r} ({last_err}).")


class DaemonRuntimeStatus:
    """Live view of a daemon record."""

    def __init__(self, record: DaemonRecord, state_path: Path) -> None:
        self.record = record
        self.state_path = state_path

    def backend_alive(self) -> bool:
        return _pid_alive(self.record.backend_pid)

    def frontend_alive(self) -> bool:
        return _pid_alive(self.record.frontend_pid)

    def alive(self) -> bool:
        return self.backend_alive() and self.frontend_alive()


def iter_daemon_records() -> list[DaemonRuntimeStatus]:
    out: list[DaemonRuntimeStatus] = []
    inst = instances_dir()
    for path in sorted(inst.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            rec = DaemonRecord.from_json_dict(data)
            out.append(DaemonRuntimeStatus(rec, path))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


def _write_record(rec: DaemonRecord) -> Path:
    inst = instances_dir()
    path = inst / f"{rec.id}.json"
    path.write_text(json.dumps(rec.to_json_dict(), indent=2), encoding="utf-8")
    return path


def _try_acquire_start_lock() -> object | None:
    """Best-effort flock so concurrent starts don't grab the same port."""
    try:
        import fcntl  # noqa: PLC0415 — optional dependency pattern on Unix only

        daemon_runtime_root().mkdir(parents=True, exist_ok=True)
        lock_file = open(_lock_path(), "a+", encoding="utf-8")  # noqa: SIM115 — kept open until release
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        return lock_file
    except OSError:
        return None


def _release_start_lock(lock_file: object | None) -> None:
    if lock_file is None:
        return
    try:
        import fcntl

        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        lock_file.close()
    except OSError:
        pass


def start_daemon(
    repo_root: Path | None = None,
    *,
    backend_port: int | None = None,
    frontend_port: int | None = None,
    tasks_dir: Path | None = None,
    wait_ready: bool = True,
    _wait_http_ready_fn: Callable[[str, float], None] | None = None,
    _popen: Callable[..., subprocess.Popen] | None = None,
) -> DaemonRecord:
    """Start backend + frontend in the background and persist state. Returns when processes are spawned."""
    root = validate_repo_root(repo_root or Path.cwd())
    uv = _resolve_uv()
    npm = _resolve_npm()
    wait_fn = _wait_http_ready_fn or _wait_http_ready
    popen_fn = _popen or subprocess.Popen

    lock = _try_acquire_start_lock()
    try:
        host = "127.0.0.1"
        b_port = pick_port(host, BACKEND_PORT_MIN, BACKEND_PORT_MAX, preferred=backend_port)
        f_port = pick_port(host, FRONTEND_PORT_MIN, FRONTEND_PORT_MAX, preferred=frontend_port)
    finally:
        _release_start_lock(lock)

    instance_id = str(uuid.uuid4())
    logs_dir = daemon_runtime_root() / "logs" / instance_id
    logs_dir.mkdir(parents=True, exist_ok=True)
    backend_log = logs_dir / "backend.log"
    frontend_log = logs_dir / "frontend.log"

    backend_url = f"http://{host}:{b_port}/"
    proxy_target = f"http://{host}:{b_port}"

    env_backend = os.environ.copy()
    if tasks_dir is not None:
        env_backend["DEV_TASKS_DIR"] = str(tasks_backend_dir(tasks_dir))

    backend_stdout = open(backend_log, "ab", buffering=0)  # noqa: SIM115
    backend_stderr = open(backend_log, "ab", buffering=0)  # noqa: SIM115
    try:
        backend_cmd = [
            uv,
            "run",
            "--project",
            str(root / "dev-server"),
            "uvicorn",
            "dev_server.main:app",
            "--reload",
            "--host",
            host,
            "--port",
            str(b_port),
        ]
        backend_proc = popen_fn(
            backend_cmd,
            cwd=str(root),
            env=env_backend,
            stdin=subprocess.DEVNULL,
            stdout=backend_stdout,
            stderr=backend_stderr,
            start_new_session=True,
        )
    except OSError as e:
        backend_stdout.close()
        backend_stderr.close()
        raise DaemonError(f"Failed to start backend: {e}") from e

    if wait_ready:
        try:
            wait_fn(backend_url, READY_TIMEOUT_S)
        except DaemonError:
            _terminate_pid(backend_proc.pid)
            backend_stdout.close()
            backend_stderr.close()
            raise

    env_frontend = os.environ.copy()
    env_frontend["VITE_DEV_PROXY_TARGET"] = proxy_target

    frontend_stdout = open(frontend_log, "ab", buffering=0)  # noqa: SIM115
    frontend_stderr = open(frontend_log, "ab", buffering=0)  # noqa: SIM115
    try:
        frontend_cmd = [npm, "run", "dev", "--", "--port", str(f_port), "--host", host]
        frontend_proc = popen_fn(
            frontend_cmd,
            cwd=str(root / "dev-frontend"),
            env=env_frontend,
            stdin=subprocess.DEVNULL,
            stdout=frontend_stdout,
            stderr=frontend_stderr,
            start_new_session=True,
        )
    except OSError as e:
        _terminate_pid(backend_proc.pid)
        backend_stdout.close()
        backend_stderr.close()
        frontend_stdout.close()
        frontend_stderr.close()
        raise DaemonError(f"Failed to start frontend: {e}") from e

    # Parent closes handles; children keep theirs open.
    backend_stdout.close()
    backend_stderr.close()
    frontend_stdout.close()
    frontend_stderr.close()

    rec = DaemonRecord(
        id=instance_id,
        repo_root=str(root),
        backend_port=b_port,
        frontend_port=f_port,
        backend_pid=backend_proc.pid,
        frontend_pid=frontend_proc.pid,
        started_at=time.time(),
        dev_cli_path=_dev_cli_path(),
        uv_path=uv,
        npm_path=npm,
        backend_log=str(backend_log),
        frontend_log=str(frontend_log),
    )
    _write_record(rec)
    return rec


def tasks_backend_dir(tasks_dir: Path) -> Path:
    """Normalize tasks directory path for DEV_TASKS_DIR."""
    return tasks_dir.expanduser().resolve()


def stop_daemon(
    daemon_id: str | None = None,
    *,
    repo_root: Path | None = None,
    stop_all: bool = False,
) -> list[str]:
    """Stop matching daemon(s). Returns stopped instance ids."""
    if stop_all:
        stopped: list[str] = []
        for st in iter_daemon_records():
            if st.backend_alive() or st.frontend_alive():
                _stop_one(st)
                stopped.append(st.record.id)
            try:
                st.state_path.unlink(missing_ok=True)
            except OSError:
                pass
        return stopped

    matches = iter_daemon_records()
    if daemon_id:
        matches = [s for s in matches if s.record.id == daemon_id]
        if not matches:
            raise DaemonError(f"No daemon with id {daemon_id!r}.")
        st = matches[0]
        _stop_one(st)
        try:
            st.state_path.unlink(missing_ok=True)
        except OSError:
            pass
        return [st.record.id]

    if repo_root is not None:
        resolved = repo_root.expanduser().resolve()
        same_repo = [s for s in matches if Path(s.record.repo_root).resolve() == resolved]
        if not same_repo:
            raise DaemonError(f"No daemon state for repo root {resolved}.")
        # Prefer still-running instances
        running = [s for s in same_repo if s.backend_alive() or s.frontend_alive()]
        pick = max(running or same_repo, key=lambda s: s.record.started_at)
        _stop_one(pick)
        try:
            pick.state_path.unlink(missing_ok=True)
        except OSError:
            pass
        return [pick.record.id]

    raise DaemonError("Specify --id, --repo-root, or --all.")


def _stop_one(st: DaemonRuntimeStatus) -> None:
    _terminate_pid(st.record.frontend_pid)
    _terminate_pid(st.record.backend_pid)


def _terminate_pid(pid: int) -> None:
    if not _pid_alive(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def list_daemons_json() -> list[dict]:
    """Return daemon rows for JSON output."""
    rows: list[dict] = []
    for st in iter_daemon_records():
        r = st.record
        rows.append(
            {
                "id": r.id,
                "repo_root": r.repo_root,
                "backend_port": r.backend_port,
                "frontend_port": r.frontend_port,
                "backend_running": st.backend_alive(),
                "frontend_running": st.frontend_alive(),
                "dev_cli_path": r.dev_cli_path,
                "uv_path": r.uv_path,
                "npm_path": r.npm_path,
                "backend_log": r.backend_log,
                "frontend_log": r.frontend_log,
                "started_at": r.started_at,
            }
        )
    return rows


def human_status(st: DaemonRuntimeStatus) -> str:
    if st.alive():
        return "running"
    if st.backend_alive() or st.frontend_alive():
        return "partial"
    return "stopped"


_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def normalize_daemon_id(raw: str) -> str:
    s = raw.strip()
    if not _ID_RE.match(s):
        raise DaemonError(f"Invalid daemon id: {raw!r}.")
    return s.lower()
