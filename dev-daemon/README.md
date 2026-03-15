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

- **Backend:** dev-server on `127.0.0.1:8000` (uvicorn with `--reload`).
- **Frontend:** Vite on http://localhost:5173 (proxies `/api` to the backend).

Open http://localhost:5173 to use the web UI.

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

Useful commands: `systemctl --user start dev-daemon.service`, `systemctl --user stop dev-daemon.service`, `journalctl --user -u dev-daemon.service -f`, `systemctl --user disable dev-daemon.service`.

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
