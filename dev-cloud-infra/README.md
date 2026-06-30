# dev-cloud-infra

AWS CDK stack for the cloud dev control plane (`us-east-1`).

## One-command deploy

From the `dev` repo root (requires AWS credentials, Node.js, `uv`, and `npm`):

```bash
./dev-cloud-infra/scripts/deploy.sh
```

This will:

1. Package the Lambda bundle (`dev-cloud-control` + `dev-sdk`)
2. Deploy or update the CDK stack (API, DynamoDB, S3, Cognito, CloudFront)
3. Build the frontend in cloud mode with Cognito env vars from stack outputs
4. Sync static assets to the SPA S3 bucket and invalidate CloudFront

### Partial deploys

```bash
./dev-cloud-infra/scripts/deploy.sh --backend   # CDK / Lambda only
./dev-cloud-infra/scripts/deploy.sh --frontend    # UI only (uses .deploy-outputs.json)
```

Stack outputs are saved to `dev-cloud-infra/.deploy-outputs.json` (gitignored).

### After first deploy

Create a Cognito user manually (admin-only signup). Install the worker on EC2:

```bash
export CONTROL_PLANE_URL=https://YOUR_CLOUDFRONT_DOMAIN/api
./dev-cloud-worker/install.sh
```

## Manual CDK deploy

```bash
./dev-cloud-infra/scripts/package-lambda.sh
cd dev-cloud-infra && uv pip install -e . && npx aws-cdk deploy
```
