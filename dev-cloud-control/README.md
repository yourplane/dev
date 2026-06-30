# dev-cloud-control

Serverless API handlers for cloud dev: tasks, comms, feed, commands, archives, PR actions, and worker routes.

Persists metadata in DynamoDB and comms/log blobs in S3. Mirrors the `dev-server` REST contract under `/api`.

## Worker routes (IAM, no Cognito JWT)

- `POST /worker/poll` — heartbeat, claim queued work, list pending deletions
- `POST /worker/tasks/{task}/sync` — bidirectional comms merge
- `POST /worker/tasks/{task}/logs` — append log chunks for live UI
- `POST /worker/tasks/{task}/command/complete` — finish command
- `POST /worker/git-token` — short-lived GitHub token broker

## Environment variables

- `DEV_CLOUD_TABLE` — DynamoDB table name (default `dev-cloud`)
- `DEV_CLOUD_BUCKET` — S3 bucket for comms and logs
