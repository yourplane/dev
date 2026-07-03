#!/usr/bin/env bash
# Deploy dev-cloud backend (CDK) and frontend (S3 + CloudFront invalidation).
#
# Usage:
#   ./scripts/deploy.sh              # full deploy (backend + frontend)
#   ./scripts/deploy.sh --backend    # Lambda + CDK stack only
#   ./scripts/deploy.sh --frontend   # frontend only (uses saved stack outputs)
#
# Environment:
#   AWS_REGION          default us-east-1
#   DEV_CLOUD_STACK     default DevCloudStack
#   CDK_REQUIRE_APPROVAL default never
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$INFRA_DIR/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/dev-frontend"
OUTPUTS_FILE="$INFRA_DIR/.deploy-outputs.json"

REGION="${AWS_REGION:-us-east-1}"
STACK_NAME="${DEV_CLOUD_STACK:-DevCloudStack}"
CDK_REQUIRE_APPROVAL="${CDK_REQUIRE_APPROVAL:-never}"

DEPLOY_BACKEND=1
DEPLOY_FRONTEND=1

for arg in "$@"; do
  case "$arg" in
    --backend) DEPLOY_FRONTEND=0 ;;
    --frontend) DEPLOY_BACKEND=0 ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 1
      ;;
  esac
done

log() { echo "==> $*"; }

fetch_stack_outputs() {
  aws cloudformation describe-stacks \
    --region "$REGION" \
    --stack-name "$STACK_NAME" \
    --query 'Stacks[0].Outputs' \
    --output json
}

if [[ "$DEPLOY_BACKEND" -eq 1 ]]; then
  log "Packaging Lambda bundle"
  "$SCRIPT_DIR/package-lambda.sh"

  log "Installing CDK app dependencies"
  (
    cd "$REPO_ROOT"
    uv pip install -q -e "$INFRA_DIR" -e "$REPO_ROOT/dev-cloud-control" -e "$REPO_ROOT/dev-sdk"
  )

  log "Deploying CDK stack ($STACK_NAME) in $REGION"
  (
    cd "$INFRA_DIR"
    export AWS_REGION="$REGION"
    export CDK_DEFAULT_REGION="$REGION"
    export CDK_DEFAULT_ACCOUNT
    CDK_DEFAULT_ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
    if ! aws ssm get-parameter --name /cdk-bootstrap/hnb659fds/version --region "$REGION" >/dev/null 2>&1; then
      log "Bootstrapping CDK in $REGION (first deploy only)"
      npx --yes aws-cdk@2 bootstrap "aws://$CDK_DEFAULT_ACCOUNT/$REGION"
    fi
    npx --yes aws-cdk@2 deploy "$STACK_NAME" \
      --require-approval "$CDK_REQUIRE_APPROVAL" \
      --outputs-file "$OUTPUTS_FILE"
  )
else
  if [[ ! -f "$OUTPUTS_FILE" ]]; then
    log "Fetching stack outputs from CloudFormation"
    fetch_stack_outputs | python3 -c "
import json, sys
outputs = json.load(sys.stdin)
path = sys.argv[1]
with open(path, 'w', encoding='utf-8') as f:
    json.dump({o['OutputKey']: o['OutputValue'] for o in outputs}, f, indent=2)
    f.write('\n')
" "$OUTPUTS_FILE"
  fi
fi

if [[ ! -f "$OUTPUTS_FILE" ]]; then
  echo "Missing deploy outputs at $OUTPUTS_FILE" >&2
  exit 1
fi

# shellcheck disable=SC2046
eval "$(python3 - "$OUTPUTS_FILE" "$STACK_NAME" <<'PY'
import json, sys
raw = json.load(open(sys.argv[1], encoding="utf-8"))
stack = sys.argv[2]
data = raw.get(stack, raw) if isinstance(raw, dict) else raw
if not isinstance(data, dict):
    raise SystemExit("Invalid deploy outputs file")
for k, v in data.items():
    print(f'export {k}="{v}"')
PY
)"

if [[ "$DEPLOY_FRONTEND" -eq 1 ]]; then
  if [[ -z "${SpaBucketName:-}" || -z "${UserPoolId:-}" || -z "${UserPoolClientId:-}" ]]; then
    echo "Stack outputs missing SpaBucketName/UserPoolId/UserPoolClientId" >&2
    exit 1
  fi

  log "Building frontend (cloud mode)"
  (
    cd "$FRONTEND_DIR"
    npm install --no-audit --no-fund
    VITE_CLOUD_MODE=true \
    VITE_AWS_REGION="$REGION" \
    VITE_COGNITO_USER_POOL_ID="$UserPoolId" \
    VITE_COGNITO_CLIENT_ID="$UserPoolClientId" \
    VITE_DEV_SERVER_URL=/api \
    npm run build
  )

  log "Uploading frontend to s3://$SpaBucketName"
  aws s3 sync "$FRONTEND_DIR/dist/" "s3://$SpaBucketName/" \
    --region "$REGION" \
    --delete \
    --cache-control "public,max-age=31536000,immutable" \
    --exclude "index.html"
  aws s3 cp "$FRONTEND_DIR/dist/index.html" "s3://$SpaBucketName/index.html" \
    --region "$REGION" \
    --cache-control "no-cache, no-store, must-revalidate" \
    --content-type "text/html"

  if [[ -n "${CloudFrontDistributionId:-}" ]]; then
    log "Invalidating CloudFront distribution $CloudFrontDistributionId"
    aws cloudfront create-invalidation \
      --distribution-id "$CloudFrontDistributionId" \
      --paths "/*" \
      --query 'Invalidation.Id' \
      --output text
  fi
fi

log "Deploy complete"
if [[ -n "${CloudFrontUrl:-}" ]]; then
  echo ""
  echo "Cloud URL: $CloudFrontUrl"
  echo "API (direct): ${ApiUrl:-}"
  echo "Cognito User Pool: ${UserPoolId:-}"
  echo "Outputs saved: $OUTPUTS_FILE"
  if [[ -n "${CursorApiKeySecretName:-}" ]]; then
    echo ""
    echo "Cursor API key secret: $CursorApiKeySecretName"
    echo "  Set value: $SCRIPT_DIR/set-cursor-api-key.sh"
    echo "  (or: aws secretsmanager put-secret-value --secret-id $CursorApiKeySecretName --secret-string 'YOUR_KEY')"
  fi
fi
