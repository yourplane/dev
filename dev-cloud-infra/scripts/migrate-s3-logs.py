#!/usr/bin/env python3
"""One-time migration: copy existing S3 agent logs into DynamoDB stream storage."""

from __future__ import annotations

import os
import sys

import boto3
from botocore.exceptions import ClientError


def main() -> int:
    bucket = os.environ.get("DEV_CLOUD_BUCKET")
    table_name = os.environ.get("DEV_CLOUD_TABLE", "dev-cloud")
    if not bucket:
        print("DEV_CLOUD_BUCKET is required", file=sys.stderr)
        return 1

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "dev-cloud-control", "src"))
    from dev_cloud_control.store import CloudStore

    store = CloudStore()
    s3 = boto3.client("s3")
    prefix = "tasks/"
    paginator = s3.get_paginator("list_objects_v2")
    migrated = 0
    skipped = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if "/logs/" not in key:
                continue
            parts = key.split("/")
            if len(parts) < 4:
                continue
            task_name = parts[1]
            filename = parts[-1]
            if store.get_stream_size(task_name, "log", filename) > 0:
                skipped += 1
                continue
            try:
                resp = s3.get_object(Bucket=bucket, Key=key)
                body = resp["Body"].read()
            except ClientError:
                continue
            if not body:
                skipped += 1
                continue
            store.import_stream_from_bytes(task_name, "log", filename, body)
            migrated += 1
            print(f"migrated {task_name}/{filename} ({len(body)} bytes)")
    print(f"done: migrated={migrated} skipped={skipped} table={table_name} bucket={bucket}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
