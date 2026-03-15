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

To run the dev stack at login or boot, use one of the options below. The script stays in the foreground, so run it under a service manager or in a dedicated terminal/session.

### systemd (user service)

Install a user unit so the daemon starts when you log in and stops when you log out:

1. Create the unit directory:
   ```bash
   mkdir -p ~/.config/systemd/user
   ```

2. Create `~/.config/systemd/user/dev-daemon.service` (see [dev-daemon.service.example](dev-daemon.service.example) in this directory). Set `WorkingDirectory` and `ExecStart` to your dev repo path.

3. Enable and start:
   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now dev-daemon.service
   ```

4. View logs: `journalctl --user -u dev-daemon.service -f`

### Shell (login session)

To start the daemon when you open a terminal, add to `~/.bashrc` or `~/.profile`:

```bash
# Start dev stack in background (optional; remove if you prefer to run manually)
# (cd /path/to/dev && ./dev-daemon/start.sh) &
```

Running in the background with `&` detaches it from the shell; to stop it you’d need to find and kill the processes. Prefer the systemd user service for a clean start/stop and logging.
