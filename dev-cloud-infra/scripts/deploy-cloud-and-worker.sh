#!/usr/bin/env bash
# Full cloud dev deploy: control plane (CDK + frontend), push branch, worker update via SSM.
#
# Usage (from dev repo root):
#   ./dev-cloud-infra/scripts/deploy-cloud-and-worker.sh
#
# Environment:
#   AWS_REGION              default us-east-1
#   DEV_CLOUD_STACK         default DevCloudStack
#   WORKER_INSTANCE_NAME    default dev-environment (EC2 Name tag)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$INFRA_DIR/.." && pwd)"
OUTPUTS_FILE="$INFRA_DIR/.deploy-outputs.json"

REGION="${AWS_REGION:-us-east-1}"
STACK_NAME="${DEV_CLOUD_STACK:-DevCloudStack}"
WORKER_INSTANCE_NAME="${WORKER_INSTANCE_NAME:-dev-environment}"
SSM_POLL_INTERVAL="${SSM_POLL_INTERVAL:-5}"

log() { echo "==> $*"; }

die() { echo "ERROR: $*" >&2; exit 1; }

require_clean_worktree() {
  if ! git -C "$REPO_ROOT" diff --quiet || ! git -C "$REPO_ROOT" diff --cached --quiet; then
    die "Working tree has uncommitted changes; commit or stash before pushing"
  fi
  if [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
    die "Working tree is dirty; commit or stash before pushing"
  fi
}

resolve_branch() {
  git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD
}

read_control_plane_url() {
  if [[ ! -f "$OUTPUTS_FILE" ]]; then
    die "Missing deploy outputs at $OUTPUTS_FILE"
  fi
  python3 - "$OUTPUTS_FILE" "$STACK_NAME" <<'PY'
import json, sys
path, stack = sys.argv[1], sys.argv[2]
raw = json.load(open(path, encoding="utf-8"))
data = raw.get(stack, raw) if isinstance(raw, dict) else raw
url = data.get("CloudFrontUrl", "")
if not url:
    raise SystemExit("CloudFrontUrl missing from deploy outputs")
print(f"{url.rstrip('/')}/api")
PY
}

lookup_instance_id() {
  local instance_id
  instance_id="$(aws ec2 describe-instances \
    --region "$REGION" \
    --filters "Name=tag:Name,Values=$WORKER_INSTANCE_NAME" "Name=instance-state-name,Values=running" \
    --query 'Reservations[0].Instances[0].InstanceId' \
    --output text)"
  if [[ -z "$instance_id" || "$instance_id" == "None" ]]; then
    die "No running EC2 instance with Name tag=$WORKER_INSTANCE_NAME in $REGION"
  fi
  echo "$instance_id"
}

wait_for_ssm_command() {
  local command_id="$1"
  local instance_id="$2"
  local status detail

  log "Waiting for SSM command $command_id on $instance_id"
  while true; do
    status="$(aws ssm get-command-invocation \
      --region "$REGION" \
      --command-id "$command_id" \
      --instance-id "$instance_id" \
      --query Status \
      --output text 2>/dev/null || echo Pending)"
    case "$status" in
      Success)
        log "SSM command succeeded"
        return 0
        ;;
      Failed|Cancelled|TimedOut)
        detail="$(aws ssm get-command-invocation \
          --region "$REGION" \
          --command-id "$command_id" \
          --instance-id "$instance_id" \
          --query '[StatusDetails,StandardErrorContent,StandardOutputContent]' \
          --output text 2>/dev/null || true)"
        die "SSM command $status: $detail"
        ;;
      Pending|InProgress|Delayed)
        sleep "$SSM_POLL_INTERVAL"
        ;;
      *)
        die "Unexpected SSM status: $status"
        ;;
    esac
  done
}

DEV_REPO_BRANCH="$(resolve_branch)"
log "Deploy branch: $DEV_REPO_BRANCH"

log "Deploying cloud control plane (backend + frontend)"
"$SCRIPT_DIR/deploy.sh"

CONTROL_PLANE_URL="$(read_control_plane_url)"
log "Control plane URL: $CONTROL_PLANE_URL"

require_clean_worktree

log "Pushing $DEV_REPO_BRANCH to origin"
git -C "$REPO_ROOT" push origin "$DEV_REPO_BRANCH"

INSTANCE_ID="$(lookup_instance_id)"
log "Worker instance: $INSTANCE_ID (Name=$WORKER_INSTANCE_NAME)"

log "Sending SSM update-worker command"
COMMAND_ID="$(aws ssm send-command \
  --region "$REGION" \
  --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --comment "deploy-cloud-and-worker: branch=$DEV_REPO_BRANCH" \
  --parameters "$(jq -n \
    --arg branch "$DEV_REPO_BRANCH" \
    --arg url "$CONTROL_PLANE_URL" \
    '{commands: ["sudo -u ubuntu -H bash -lc \"export DEV_REPO_BRANCH=\($branch) CONTROL_PLANE_URL=\($url) && cd ~/dev/dev-cloud-worker && ./update-worker.sh\""]}')" \
  --query Command.CommandId \
  --output text)"

wait_for_ssm_command "$COMMAND_ID" "$INSTANCE_ID"

log "Cloud + worker deploy complete"
echo "  Branch: $DEV_REPO_BRANCH"
echo "  Control plane: $CONTROL_PLANE_URL"
echo "  Worker instance: $INSTANCE_ID"
