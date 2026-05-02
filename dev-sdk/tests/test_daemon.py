"""Tests for dev_sdk.daemon."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dev_sdk import daemon as d


@pytest.fixture
def xdg_daemon_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    data = tmp_path / "xdg-data"
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    return data / "dev" / "daemon"


def test_validate_repo_root_ok(tmp_path: Path) -> None:
    root = tmp_path / "dev-workspace"
    (root / "dev-server").mkdir(parents=True)
    (root / "dev-frontend").mkdir(parents=True)
    assert d.validate_repo_root(root) == root.resolve()


def test_validate_repo_root_missing(tmp_path: Path) -> None:
    root = tmp_path / "bad"
    root.mkdir()
    with pytest.raises(d.DaemonError, match="dev-server"):
        d.validate_repo_root(root)


def test_pick_port_prefers_available(xdg_daemon_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(d, "port_available", lambda host, port, exclude_daemon_ports=True: port == 28431)
    assert d.pick_port("127.0.0.1", d.BACKEND_PORT_MIN, d.BACKEND_PORT_MAX) == 28431


def test_pick_port_explicit_ok(xdg_daemon_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(d, "port_available", lambda host, port, exclude_daemon_ports=True: True)
    p = d.pick_port("127.0.0.1", d.BACKEND_PORT_MIN, d.BACKEND_PORT_MAX, preferred=28440)
    assert p == 28440


def test_pick_port_explicit_unavailable(xdg_daemon_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(d, "port_available", lambda host, port, exclude_daemon_ports=True: False)
    with pytest.raises(d.DaemonError, match="not available"):
        d.pick_port("127.0.0.1", d.BACKEND_PORT_MIN, d.BACKEND_PORT_MAX, preferred=28440)


def test_normalize_daemon_id() -> None:
    u = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert d.normalize_daemon_id(u) == u
    with pytest.raises(d.DaemonError, match="Invalid"):
        d.normalize_daemon_id("not-a-uuid")


def test_start_daemon_writes_state(
    xdg_daemon_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "ws"
    (root / "dev-server").mkdir(parents=True)
    (root / "dev-frontend").mkdir(parents=True)

    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))
    monkeypatch.setattr(d, "_resolve_uv", lambda: "/bin/uv")
    monkeypatch.setattr(d, "_resolve_npm", lambda: "/bin/npm")
    monkeypatch.setattr(d, "_dev_cli_path", lambda: "/bin/dev")

    pids = iter(range(90000, 91000))

    def fake_popen(cmd: list, **kwargs):  # noqa: ANN001
        m = MagicMock()
        m.pid = next(pids)
        return m

    rec = d.start_daemon(
        root,
        wait_ready=False,
        _wait_http_ready_fn=lambda url, timeout_s: None,
        _popen=fake_popen,
    )

    assert rec.repo_root == str(root.resolve())
    assert d.BACKEND_PORT_MIN <= rec.backend_port <= d.BACKEND_PORT_MAX
    assert d.FRONTEND_PORT_MIN <= rec.frontend_port <= d.FRONTEND_PORT_MAX

    inst = xdg_daemon_home / "instances"
    files = list(inst.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["id"] == rec.id
    assert data["uv_path"] == "/bin/uv"
    assert data["npm_path"] == "/bin/npm"
    assert data["dev_cli_path"] == "/bin/dev"


def test_stop_daemon_by_id_removes_state(
    xdg_daemon_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "ws"
    (root / "dev-server").mkdir(parents=True)
    (root / "dev-frontend").mkdir(parents=True)
    monkeypatch.setattr(d, "_resolve_uv", lambda: "/bin/uv")
    monkeypatch.setattr(d, "_resolve_npm", lambda: "/bin/npm")
    monkeypatch.setattr(d, "_dev_cli_path", lambda: "/bin/dev")

    pids = iter(range(92000, 93000))

    def fake_popen(cmd: list, **kwargs):  # noqa: ANN001
        m = MagicMock()
        m.pid = next(pids)
        return m

    terminated: list[int] = []

    def fake_term(pid: int) -> None:
        terminated.append(pid)

    monkeypatch.setattr(d, "_terminate_pid", fake_term)
    monkeypatch.setattr(d, "_pid_alive", lambda pid: False)

    rec = d.start_daemon(
        root,
        wait_ready=False,
        _wait_http_ready_fn=lambda url, timeout_s: None,
        _popen=fake_popen,
    )

    stopped = d.stop_daemon(rec.id)
    assert stopped == [rec.id]
    inst = xdg_daemon_home / "instances"
    assert list(inst.glob("*.json")) == []
    assert terminated == [rec.frontend_pid, rec.backend_pid]


def test_list_daemons_json_roundtrip(
    xdg_daemon_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "ws"
    (root / "dev-server").mkdir(parents=True)
    (root / "dev-frontend").mkdir(parents=True)
    monkeypatch.setattr(d, "_resolve_uv", lambda: "/bin/uv")
    monkeypatch.setattr(d, "_resolve_npm", lambda: "/bin/npm")
    monkeypatch.setattr(d, "_dev_cli_path", lambda: "/bin/dev")
    monkeypatch.setattr(d, "_pid_alive", lambda pid: False)

    pids = iter(range(93000, 94000))

    def fake_popen(cmd: list, **kwargs):  # noqa: ANN001
        m = MagicMock()
        m.pid = next(pids)
        return m

    rec = d.start_daemon(
        root,
        wait_ready=False,
        _wait_http_ready_fn=lambda url, timeout_s: None,
        _popen=fake_popen,
    )
    rows = d.list_daemons_json()
    assert len(rows) == 1
    assert rows[0]["id"] == rec.id
    assert "backend_port" in rows[0]
    assert "dev_cli_path" in rows[0]
