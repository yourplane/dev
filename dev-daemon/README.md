# dev-daemon

Legacy shell helpers were removed. Use the **`dev` CLI** to run multiple concurrent stacks (each with its own backend and frontend ports):

```bash
cd /path/to/dev   # repo root containing dev-server and dev-frontend

dev daemon start              # background; prints URLs and instance id
dev daemon list               # status, ports, paths to dev/uv/npm
dev daemon stop --id <uuid>   # or --repo-root . / --all
```

Ports are auto-selected from uncommon ranges (see `dev_sdk.daemon`). Override with `--backend-port` / `--frontend-port` when needed.

For systemd or login startup, point **`ExecStart`** at `dev daemon start` with **`WorkingDirectory`** set to this repo root (same environment as a normal shell: `PATH` must include `uv`, `npm`, and `dev`).
