"""Tests for cloud control plane routing."""

from __future__ import annotations

import json
import os

import boto3
import pytest
from moto import mock_aws

from dev_cloud_control.handler import Router
from dev_cloud_control.store import CloudStore


@pytest.fixture
def aws_env():
    with mock_aws():
        os.environ["DEV_CLOUD_TABLE"] = "dev-cloud-test"
        os.environ["DEV_CLOUD_BUCKET"] = "dev-cloud-test-bucket"
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName="dev-cloud-test",
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
                {"AttributeName": "entity", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "entity-index",
                    "KeySchema": [
                        {"AttributeName": "entity", "KeyType": "HASH"},
                        {"AttributeName": "pk", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="dev-cloud-test-bucket")
        yield


def _event(method: str, path: str, body: dict | None = None) -> dict:
    ev = {
        "requestContext": {"http": {"method": method}},
        "rawPath": f"/api{path}",
        "rawQueryString": "",
    }
    if body is not None:
        ev["body"] = json.dumps(body)
    return ev


def test_worker_poll_registers_environment(aws_env):
    router = Router()
    resp = router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1"}))
    assert resp["statusCode"] == 200
    data = json.loads(resp["body"])
    assert data["environment_id"] == "env-1"


def test_create_task_queues_command(aws_env):
    router = Router()
    router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1", "display_name": "Test"}))
    resp = router.dispatch(
        _event(
            "POST",
            "/tasks",
            {"title": "My Task", "environment_id": "env-1", "repo": None},
        )
    )
    assert resp["statusCode"] == 200
    lines = [json.loads(ln) for ln in resp["body"].strip().split("\n") if ln]
    assert any(l["type"] == "complete" for l in lines)
    poll = router.dispatch(_event("POST", "/worker/poll", {"environment_id": "env-1"}))
    work = json.loads(poll["body"])["work"]
    assert any(w["command"]["command"] == "create-task" for w in work)


def test_repos_crud(aws_env):
    router = Router()
    resp = router.dispatch(_event("POST", "/repos", {"name": "dev", "url": "https://github.com/o/r.git"}))
    assert resp["statusCode"] == 200
    repos = json.loads(router.dispatch(_event("GET", "/repos"))["body"])
    assert repos["dev"] == "https://github.com/o/r.git"
