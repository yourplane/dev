# dev-cloud-worker

Outbound-only environment worker. Polls the control plane every ~5s, executes queued commands locally via `dev-sdk`, syncs comms, and streams agent logs to the cloud.

## Install (EC2)

```bash
export CONTROL_PLANE_URL=https://YOUR_CLOUDFRONT/api
export DEV_TASKS_ROOT=$HOME/tasks
./install.sh
```

The worker stores its `environment_id` in `~/.config/dev-cloud/environment_id`. Uses the EC2 instance IAM role for worker API calls (no static keys).
