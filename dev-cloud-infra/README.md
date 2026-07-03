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

**Cognito users** — Admin-created users with a temporary password must set a new password on first sign-in (the UI handles this automatically). Invitation emails use Cognito’s built-in sender (limited deliverability); if email doesn’t arrive, create the user with a known password via CLI:

```bash
aws cognito-idp admin-create-user \
  --user-pool-id <UserPoolId> \
  --username YOU@example.com \
  --user-attributes Name=email,Value=YOU@example.com Name=email_verified,Value=true \
  --temporary-password 'ChangeMeNow123!' \
  --message-action SUPPRESS
aws cognito-idp admin-set-user-password \
  --user-pool-id <UserPoolId> \
  --username YOU@example.com \
  --password 'YourSecurePassword12!' \
  --permanent
```

Or skip the second command and sign in with the temporary password — the UI will prompt for a new permanent password.

Install the worker on EC2:

```bash
export CONTROL_PLANE_URL=https://YOUR_CLOUDFRONT_DOMAIN/api
./dev-cloud-worker/install.sh
```

**Cursor API key** — CDK creates Secrets Manager secret `dev-cloud/cursor-api-key`. After deploy, set your personal key:

```bash
./dev-cloud-infra/scripts/set-cursor-api-key.sh
```

On the workstation, run `./dev-cloud-worker/wire-cursor-environment.sh` (or re-run bootstrap after the key is set).

## Manual CDK deploy

```bash
./dev-cloud-infra/scripts/package-lambda.sh
cd dev-cloud-infra && uv pip install -e . && npx aws-cdk deploy
```
