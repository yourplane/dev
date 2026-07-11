"""Shared bash streaming execution (timeout, truncation, stdbuf, cancel)."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from dev_sdk.comms import add_comms, bash_comms_input_header, begin_streaming_bash_comms

logger = logging.getLogger(__name__)

DEFAULT_BASH_MAX_OUTPUT_BYTES = 2_000_000
DEFAULT_BASH_TIMEOUT_SEC = 3600.0

_bash_comms_append_lock = threading.Lock()


@dataclass(frozen=True)
class BashRunResult:
    exit_code: int | None
    cancelled: bool
    timed_out: bool
    truncated: bool
    comms_path: Path | None = None


@dataclass
class BashStreamConfig:
    max_output_bytes: int = DEFAULT_BASH_MAX_OUTPUT_BYTES
    timeout_sec: float = DEFAULT_BASH_TIMEOUT_SEC
    use_stdbuf: bool | None = None


@dataclass
class BashStreamHooks:
    """Optional callbacks for runtime-specific behavior (registry, log upload)."""

    on_comms_path: Callable[[Path], None] | None = None
    on_output_appended: Callable[[Path], None] | None = None


def append_bytes_to_bash_comms(path: Path, data: bytes) -> None:
    with _bash_comms_append_lock:
        with open(path, "ab") as f:
            f.write(data)


def append_bash_comms_footer(
    path: Path,
    *,
    truncated: bool,
    cancelled: bool,
    timed_out: bool,
    exit_code: int | None,
    timeout_sec: float,
    interrupted: bool = False,
) -> None:
    with _bash_comms_append_lock:
        with open(path, "a", encoding="utf-8") as f:
            if truncated:
                f.write("\n[… output truncated (DEV_BASH_MAX_OUTPUT_BYTES) …]")
            f.write("\n---\n")
            if interrupted:
                f.write("Interrupted.\n")
            elif cancelled:
                f.write("Cancelled by user.\n")
            elif timed_out:
                f.write(f"Timed out after {timeout_sec:g}s (DEV_BASH_TIMEOUT_SEC).\n")
            else:
                f.write(f"Exit code: {exit_code if exit_code is not None else 'unknown'}\n")


def terminate_process_group(proc: subprocess.Popen, *, use_kill: bool = False) -> None:
    """Send SIGTERM (or SIGKILL) to the child's process group."""
    try:
        sig = signal.SIGKILL if use_kill else signal.SIGTERM
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def popen_bash_for_streaming(shell_command: str, *, cwd: str, use_stdbuf: bool | None = None) -> subprocess.Popen[str]:
    """
    Spawn ``bash -c`` with stdout/stderr merged to a PIPE.

    Uses ``bufsize=0`` so Python does not wrap the pipe in a large BufferedReader
    (default ``bufsize`` blocks ``read()`` until ~8KiB accumulates or the pipe closes).

    Without a TTY, libc stdio defaults to fully buffered stdout on the child; prefer
    coreutils ``stdbuf`` line buffering when available so programs flush often enough.
    Set DEV_BASH_NO_STDBUF=1 to skip ``stdbuf`` (e.g. minimal images without coreutils).
    """
    if use_stdbuf is None:
        use_stdbuf = os.environ.get("DEV_BASH_NO_STDBUF", "").strip().lower() not in (
            "1",
            "true",
            "yes",
        )
    argv_candidates: list[list[str]] = []
    if use_stdbuf:
        argv_candidates.append(["stdbuf", "-oL", "-eL", "bash", "-c", shell_command])
    argv_candidates.append(["bash", "-c", shell_command])
    last_fe: FileNotFoundError | None = None
    for argv in argv_candidates:
        try:
            return subprocess.Popen(
                argv,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                bufsize=0,
            )
        except FileNotFoundError as e:
            last_fe = e
            continue
    assert last_fe is not None
    raise last_fe


def _resolve_config(config: BashStreamConfig | None) -> BashStreamConfig:
    if config is not None:
        return config
    try:
        max_bytes = int(
            os.environ.get("DEV_BASH_MAX_OUTPUT_BYTES", str(DEFAULT_BASH_MAX_OUTPUT_BYTES))
        )
    except ValueError:
        max_bytes = DEFAULT_BASH_MAX_OUTPUT_BYTES
    try:
        timeout_sec = float(os.environ.get("DEV_BASH_TIMEOUT_SEC", str(DEFAULT_BASH_TIMEOUT_SEC)))
    except ValueError:
        timeout_sec = DEFAULT_BASH_TIMEOUT_SEC
    return BashStreamConfig(max_output_bytes=max_bytes, timeout_sec=timeout_sec)


def run_bash_stream(
    task_dir: Path,
    shell_command: str,
    *,
    cwd: Path,
    cancel_event: threading.Event,
    hooks: BashStreamHooks | None = None,
    config: BashStreamConfig | None = None,
) -> BashRunResult:
    """
    Run bash -c with streaming comms in task_dir.

    Returns BashRunResult with exit_code, cancelled, timed_out, truncated.
    """
    cfg = _resolve_config(config)
    hooks = hooks or BashStreamHooks()

    try:
        proc = popen_bash_for_streaming(
            shell_command,
            cwd=str(cwd),
            use_stdbuf=cfg.use_stdbuf,
        )
    except OSError as exc:
        logger.warning("bash spawn failed: %s", exc)
        add_comms(
            task_dir,
            "user",
            f"{bash_comms_input_header(shell_command)}\n---\nFailed to start process: {exc}\n",
            kind="bash",
        )
        return BashRunResult(None, False, False, False, None)

    path: Path | None = None
    footer_written = False
    truncated = False
    cancelled = False
    timed_out = False
    start = time.monotonic()
    trunc_cell: list[bool] = [False]
    stdout = proc.stdout
    assert stdout is not None

    try:
        path = begin_streaming_bash_comms(task_dir, shell_command)
        if hooks.on_comms_path is not None:
            hooks.on_comms_path(path)

        collected = bytearray()

        def read_stdout() -> None:
            while True:
                chunk = stdout.read(4096)
                if not chunk:
                    break
                room = cfg.max_output_bytes - len(collected)
                if room <= 0:
                    trunc_cell[0] = True
                    break
                take = min(len(chunk), room)
                portion = chunk[:take]
                collected.extend(portion)
                append_bytes_to_bash_comms(path, portion)
                if hooks.on_output_appended is not None:
                    hooks.on_output_appended(path)
                if take < len(chunk):
                    trunc_cell[0] = True
                    break

        reader = threading.Thread(target=read_stdout, daemon=True)
        reader.start()

        try:
            while proc.poll() is None:
                if cancel_event.is_set():
                    cancelled = True
                    terminate_process_group(proc, use_kill=False)
                    break
                if cfg.timeout_sec > 0 and (time.monotonic() - start) > cfg.timeout_sec:
                    timed_out = True
                    terminate_process_group(proc, use_kill=True)
                    break
                if trunc_cell[0] or len(collected) >= cfg.max_output_bytes:
                    truncated = True
                    terminate_process_group(proc, use_kill=True)
                    break
                time.sleep(0.1)
            reader.join(timeout=30.0)
            if proc.poll() is None:
                terminate_process_group(proc, use_kill=True)
                proc.wait(timeout=15)
            else:
                proc.wait(timeout=15)
        finally:
            try:
                stdout.close()
            except OSError:
                pass

        truncated = truncated or trunc_cell[0]
        exit_code = proc.returncode
        append_bash_comms_footer(
            path,
            truncated=truncated,
            cancelled=cancelled,
            timed_out=timed_out,
            exit_code=exit_code,
            timeout_sec=cfg.timeout_sec,
        )
        if hooks.on_output_appended is not None:
            hooks.on_output_appended(path)
        footer_written = True
        return BashRunResult(exit_code, cancelled, timed_out, truncated, path)
    except Exception:
        logger.exception("bash run failed")
        if path is not None and not footer_written:
            try:
                append_bash_comms_footer(
                    path,
                    truncated=False,
                    cancelled=False,
                    timed_out=False,
                    exit_code=None,
                    timeout_sec=cfg.timeout_sec,
                    interrupted=True,
                )
                if hooks.on_output_appended is not None:
                    hooks.on_output_appended(path)
            except OSError:
                logger.exception("failed to write bash interrupted footer")
        return BashRunResult(None, cancelled, timed_out, truncated, path)
    finally:
        if path is not None and not footer_written:
            try:
                append_bash_comms_footer(
                    path,
                    truncated=False,
                    cancelled=False,
                    timed_out=False,
                    exit_code=None,
                    timeout_sec=cfg.timeout_sec,
                    interrupted=True,
                )
                if hooks.on_output_appended is not None:
                    hooks.on_output_appended(path)
            except OSError:
                logger.exception("failed to finalize bash comms")
