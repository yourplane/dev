# dev-cloud-infra

AWS CDK stack for the cloud dev control plane (`us-east-1`).

## Deploy

```bash
cd dev-cloud-infra
./scripts/package-lambda.sh
uv pip install -e .
cdk deploy
```

Outputs include Cognito pool/client IDs, CloudFront URL, and worker IAM role ARN.

Create a Cognito user manually (admin-only signup). Point the frontend at CloudFront with `VITE_CLOUD_MODE=true` and the Cognito env vars from stack outputs.
