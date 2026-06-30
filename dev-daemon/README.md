# dev-daemon

Starts the dev backend (dev-server) and frontend (dev-frontend) with one command. Run in the foreground; Ctrl+C stops both.

## Run

From the **dev repo root** (the directory that contains `dev-server`, `dev-frontend`, and `dev-daemon`):

```bash
./dev-daemon/start.sh
```

Or from anywhere, pointing at the repo:

```bash
/path/to/dev/dev-daemon/start.sh
```

### Restart

```bash
./dev-daemon/restart.sh
```

If you installed the systemd user service (`install.sh`), this runs `systemctl --user restart dev-daemon.service`. Otherwise it stops processes listening on ports **8000** (backend) and **5173** (frontend), then runs `start.sh` in the foreground.

- **Backend:** dev-server on `127.0.0.1:8000` (uvicorn; `--reload` only in `dev` frontend mode).
- **Frontend:** http://localhost:5173 — by default a **production build** served with `vite preview` (no HMR full-page reloads on mobile). Set `DEV_DAEMON_FRONTEND=dev` to use the Vite dev server with HMR for active frontend work.

Open http://localhost:5173 to use the web UI.

### Frontend mode

| `DEV_DAEMON_FRONTEND` | Behavior |
|-----------------------|----------|
| `preview` (default) | `vite build` then `vite preview` — stable for daily use and mobile |
| `dev` | `vite dev` with HMR — use while editing frontend code |

Example:

```bash
DEV_DAEMON_FRONTEND=dev ./dev-daemon/start.sh
```

## On startup

To run the dev stack at login, use the install script (systemd user service) or the manual options below.

### Install script (recommended)

From the dev repo root:

```bash
./dev-daemon/install.sh
```

This creates `~/.config/systemd/user/dev-daemon.service` with the correct paths, runs `systemctl --user daemon-reload`, and enables the service so it starts when you log in. To start immediately as well:

```bash
./dev-daemon/install.sh --now
```

Useful commands: `systemctl --user start dev-daemon.service`, `systemctl --user stop dev-daemon.service`, `systemctl --user restart dev-daemon.service`, `journalctl --user -u dev-daemon.service -f`, `systemctl --user disable dev-daemon.service`.

Or from the repo root: `./dev-daemon/restart.sh` (uses systemd when installed).

### systemd (manual)

If you prefer to install the unit by hand:

1. Create the unit directory: `mkdir -p ~/.config/systemd/user`
2. Create `~/.config/systemd/user/dev-daemon.service` with `WorkingDirectory` set to your dev repo root and `ExecStart` set to `$REPO_ROOT/dev-daemon/start.sh` (use `Type=simple`, `Restart=on-failure`, `RestartSec=5`, `WantedBy=default.target`).
3. Run `systemctl --user daemon-reload` and `systemctl --user enable --now dev-daemon.service`
4. View logs: `journalctl --user -u dev-daemon.service -f`

### Shell (login session)

To start the daemon when you open a terminal, add to `~/.bashrc` or `~/.profile`:

```bash
# Start dev stack in background (optional; remove if you prefer to run manually)
# (cd /path/to/dev && ./dev-daemon/start.sh) &
```

Running in the background with `&` detaches it from the shell; to stop it you’d need to find and kill the processes. Prefer the systemd user service for a clean start/stop and logging.
