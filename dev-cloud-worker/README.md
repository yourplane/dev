# dev-cloud-worker

Outbound-only environment worker. Polls the control plane every ~5s, executes queued commands locally via `dev-sdk`, syncs comms, and streams agent logs to the cloud.

## Install (EC2 / desk workstation)

```bash
export CONTROL_PLANE_URL=https://YOUR_CLOUDFRONT/api
export DEV_TASKS_ROOT=$HOME/tasks
export DEV_CLOUD_DISPLAY_NAME=dev-environment   # optional; shown in cloud UI
./install.sh
```

Enable linger so the worker survives logout/reboot:

```bash
sudo loginctl enable-linger $USER
```

## Bootstrap a fresh desk environment

On a new workstation (or to reinstall from scratch):

```bash
export CONTROL_PLANE_URL=https://YOUR_CLOUDFRONT/api
export DEV_REPO_BRANCH=task/cloud-dev
export DEV_CLOUD_DISPLAY_NAME=dev-environment
./bootstrap-environment.sh
```

From an operator machine via SSM (example):

```bash
INSTANCE_ID=i-xxxxxxxx
aws ssm send-command \
  --region us-east-1 \
  --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --parameters "$(jq -n --arg url 'https://xxx.cloudfront.net/api' \
    '{commands: ["sudo -u ubuntu -H env CONTROL_PLANE_URL=\($url) DEV_CLOUD_DISPLAY_NAME=dev-environment DEV_REPO_BRANCH=task/cloud-dev bash -lc \"curl -fsSL https://raw.githubusercontent.com/yourplane/dev/task/cloud-dev/dev/dev-cloud-worker/bootstrap-environment.sh | bash\""]}')"
```

Prefer cloning the repo and running `bootstrap-environment.sh` from disk after push.

The worker stores its `environment_id` in `~/.config/dev-cloud/environment_id`. Uses the EC2 instance IAM role for worker API calls (no static keys).
