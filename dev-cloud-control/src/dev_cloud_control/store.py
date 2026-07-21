"""Cloud persistence: DynamoDB entities + S3 blobs."""

from __future__ import annotations

import base64
import json
import os
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import boto3
from botocore.exceptions import ClientError

OFFLINE_THRESHOLD_SEC = 10
STREAM_CHUNK_MAX_BYTES = 250_000
COMMS_INDEX_FILE = "index.txt"
TELEMETRY_RETENTION_SEC = 3 * 3600
TELEMETRY_BUCKET_SEC = 60


def scrub_comms_index_content(raw: str) -> str:
    """Drop index.txt self-references and duplicate lines from stored index content."""
    seen: set[str] = set()
    lines: list[str] = []
    for line in raw.splitlines():
        name = line.strip()
        if not name or name == COMMS_INDEX_FILE or name in seen:
            continue
        seen.add(name)
        lines.append(name)
    return "\n".join(lines) + ("\n" if lines else "")


def _now() -> Decimal:
    return Decimal(str(time.time()))


def _ddb(value: Any) -> Any:
    """Convert floats to Decimal for DynamoDB."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _ddb(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_ddb(v) for v in value]
    return value


def _table_name() -> str:
    return os.environ.get("DEV_CLOUD_TABLE", "dev-cloud")


def _bucket_name() -> str:
    name = os.environ.get("DEV_CLOUD_BUCKET")
    if not name:
        raise RuntimeError("DEV_CLOUD_BUCKET not set")
    return name


@dataclass
class EnvironmentRecord:
    environment_id: str
    display_name: str
    registered_at: float
    last_heartbeat: float

    @property
    def online(self) -> bool:
        return (float(time.time()) - float(self.last_heartbeat)) < OFFLINE_THRESHOLD_SEC


@dataclass
class TaskRecord:
    task_name: str
    environment_id: str
    title: str
    repo: str | None = None
    owner: str | None = None
    repo_name: str | None = None
    branch: str | None = None
    status: str = "active"
    active_command: dict | None = None
    queued_command: dict | None = None
    create_progress: list[str] = field(default_factory=list)
    last_command_error: str | None = None
    comms_cloud_epoch: int = 0
    worker_comms_epoch: int = 0
    sync_health: str | None = None  # "healthy" | "unhealthy" | None


@dataclass
class FeedItem:
    type: str
    id: str
    created_at: float
    deletable: bool | None = None
    delete_status: str | None = None
    origin: str = "cloud"  # cloud | worker


@dataclass
class ArchiveRecord:
    archived_name: str
    task_name: str
    source_environment_id: str
    archived_date: str
    archived_at: str
    last_modified_at: str
    repo: str | None = None
    branch: str | None = None
    owner: str | None = None
    repo_name: str | None = None


class CloudStore:
    def __init__(self) -> None:
        self._ddb = boto3.resource("dynamodb")
        self._table = self._ddb.Table(_table_name())
        self._s3 = boto3.client("s3")
        self._bucket = _bucket_name()

    # --- environments ---

    def allocate_display_name(self, desired: str | None, environment_id: str) -> str:
        base = (desired or "").strip() or environment_id[:8]
        self._remove_offline_name_conflicts(base, environment_id)
        taken = {
            e.display_name
            for e in self.list_environments()
            if e.environment_id != environment_id
        }
        if base not in taken:
            return base
        n = 2
        while f"{base}-{n}" in taken:
            n += 1
        return f"{base}-{n}"

    def _display_name_conflicts(self, base: str, existing: str) -> bool:
        return existing == base or existing.startswith(f"{base}-")

    def _remove_offline_name_conflicts(self, base: str, keep_id: str) -> None:
        for env in list(self.list_environments()):
            if env.environment_id == keep_id:
                continue
            if not self._display_name_conflicts(base, env.display_name):
                continue
            if env.online:
                continue
            if self.count_tasks_for_environment(env.environment_id) == 0:
                self.delete_environment(env.environment_id)

    def prune_stale_duplicates(self, keep_id: str) -> None:
        keep = self.get_environment(keep_id)
        if not keep:
            return
        for env in list(self.list_environments()):
            if env.environment_id == keep_id:
                continue
            if env.display_name != keep.display_name:
                continue
            stale = not env.online or float(env.last_heartbeat) < float(keep.last_heartbeat)
            if stale and self.count_tasks_for_environment(env.environment_id) == 0:
                self.delete_environment(env.environment_id)

    def register_environment(self, environment_id: str, display_name: str | None = None) -> EnvironmentRecord:
        name = self.allocate_display_name(display_name, environment_id)
        ts = _now()
        item = {
            "pk": f"ENV#{environment_id}",
            "sk": "META",
            "entity": "environment",
            "environment_id": environment_id,
            "display_name": name,
            "registered_at": ts,
            "last_heartbeat": ts,
        }
        try:
            self._table.put_item(
                Item=_ddb(item),
                ConditionExpression="attribute_not_exists(pk)",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            self.heartbeat(environment_id)
        return self.get_environment(environment_id)  # type: ignore[return-value]

    def heartbeat(self, environment_id: str) -> None:
        self._table.update_item(
            Key={"pk": f"ENV#{environment_id}", "sk": "META"},
            UpdateExpression="SET last_heartbeat = :ts",
            ExpressionAttributeValues={":ts": _now()},
        )

    def list_environments(self) -> list[EnvironmentRecord]:
        resp = self._table.query(
            IndexName="entity-index",
            KeyConditionExpression="entity = :e",
            ExpressionAttributeValues={":e": "environment"},
        )
        return [self._env_from_item(i) for i in resp.get("Items", [])]

    def get_environment(self, environment_id: str) -> EnvironmentRecord | None:
        resp = self._table.get_item(Key={"pk": f"ENV#{environment_id}", "sk": "META"})
        item = resp.get("Item")
        return self._env_from_item(item) if item else None

    def update_environment_display_name(self, environment_id: str, display_name: str) -> str:
        unique = self.allocate_display_name(display_name, environment_id)
        self._table.update_item(
            Key={"pk": f"ENV#{environment_id}", "sk": "META"},
            UpdateExpression="SET display_name = :n",
            ExpressionAttributeValues={":n": unique},
        )
        return unique

    def _env_from_item(self, item: dict) -> EnvironmentRecord:
        return EnvironmentRecord(
            environment_id=item["environment_id"],
            display_name=item.get("display_name", ""),
            registered_at=float(item.get("registered_at", 0)),
            last_heartbeat=float(item.get("last_heartbeat", 0)),
        )

    # --- tasks ---

    def create_task(self, record: TaskRecord) -> None:
        item = {
            "pk": f"TASK#{record.task_name}",
            "sk": "META",
            "entity": "task",
            "task_name": record.task_name,
            "environment_id": record.environment_id,
            "title": record.title,
            "repo": record.repo,
            "owner": record.owner,
            "repo_name": record.repo_name,
            "branch": record.branch,
            "status": record.status,
            "active_command": record.active_command,
            "queued_command": record.queued_command,
            "create_progress": record.create_progress,
            "last_command_error": record.last_command_error,
            "comms_cloud_epoch": record.comms_cloud_epoch,
            "worker_comms_epoch": record.worker_comms_epoch,
            "sync_health": record.sync_health,
        }
        self._table.put_item(
            Item=_ddb(item),
            ConditionExpression="attribute_not_exists(pk)",
        )

    def get_task(self, task_name: str) -> TaskRecord | None:
        resp = self._table.get_item(Key={"pk": f"TASK#{task_name}", "sk": "META"})
        item = resp.get("Item")
        return self._task_from_item(item) if item else None

    def list_tasks(self) -> list[str]:
        resp = self._table.query(
            IndexName="entity-index",
            KeyConditionExpression="entity = :e",
            ExpressionAttributeValues={":e": "task"},
        )
        names = [
            i["task_name"]
            for i in resp.get("Items", [])
            if i.get("status", "active") in ("active", "pending_unarchive")
        ]
        return sorted(names)

    def update_task(self, task_name: str, **fields: Any) -> None:
        if not fields:
            return
        names: dict[str, str] = {}
        parts: list[str] = []
        values: dict[str, Any] = {}
        for i, (k, v) in enumerate(fields.items()):
            name_key = f"#k{i}"
            names[name_key] = k
            parts.append(f"{name_key} = :v{i}")
            values[f":v{i}"] = v
        params: dict[str, Any] = {
            "Key": {"pk": f"TASK#{task_name}", "sk": "META"},
            "UpdateExpression": "SET " + ", ".join(parts),
            "ExpressionAttributeValues": _ddb(values),
            "ExpressionAttributeNames": names,
        }
        self._table.update_item(**params)

    def _task_from_item(self, item: dict) -> TaskRecord:
        return TaskRecord(
            task_name=item["task_name"],
            environment_id=item["environment_id"],
            title=item.get("title", item["task_name"]),
            repo=item.get("repo"),
            owner=item.get("owner"),
            repo_name=item.get("repo_name"),
            branch=item.get("branch"),
            status=item.get("status", "active"),
            active_command=item.get("active_command"),
            queued_command=item.get("queued_command"),
            create_progress=item.get("create_progress") or [],
            last_command_error=item.get("last_command_error"),
            comms_cloud_epoch=int(item.get("comms_cloud_epoch", 0) or 0),
            worker_comms_epoch=int(item.get("worker_comms_epoch", 0) or 0),
            sync_health=item.get("sync_health"),
        )

    def bump_comms_cloud_epoch(self, task_name: str) -> int:
        task = self.get_task(task_name)
        epoch = (task.comms_cloud_epoch if task else 0) + 1
        self.update_task(task_name, comms_cloud_epoch=epoch)
        return epoch

    def mark_worker_comms_synced(self, task_name: str) -> None:
        task = self.get_task(task_name)
        if not task:
            return
        self.update_task(task_name, worker_comms_epoch=task.comms_cloud_epoch)

    # --- config ---

    def get_repos(self) -> dict[str, str]:
        resp = self._table.get_item(Key={"pk": "CONFIG", "sk": "repos"})
        item = resp.get("Item")
        if not item:
            return {}
        return dict(item.get("data", {}))

    def save_repos(self, repos: dict[str, str]) -> None:
        self._table.put_item(
            Item={"pk": "CONFIG", "sk": "repos", "entity": "config", "data": repos}
        )

    def get_bots(self) -> list[dict[str, str]]:
        resp = self._table.get_item(Key={"pk": "CONFIG", "sk": "bots"})
        item = resp.get("Item")
        if not item:
            return []
        return list(item.get("data", []))

    def save_bots(self, bots: list[dict[str, str]]) -> None:
        self._table.put_item(
            Item={"pk": "CONFIG", "sk": "bots", "entity": "config", "data": bots}
        )

    # --- drafts (DDB small text) ---

    def get_draft(self, sk: str) -> str | dict | None:
        resp = self._table.get_item(Key={"pk": "DRAFTS", "sk": sk})
        item = resp.get("Item")
        if not item:
            return None
        return item.get("data")

    def set_draft(self, sk: str, data: str | dict) -> None:
        self._table.put_item(Item={"pk": "DRAFTS", "sk": sk, "entity": "draft", "data": data})

    def delete_draft(self, sk: str) -> None:
        self._table.delete_item(Key={"pk": "DRAFTS", "sk": sk})

    # --- S3 comms/logs ---

    def _comms_key(self, task_name: str, filename: str) -> str:
        return f"tasks/{task_name}/comms/{filename}"

    def _log_key(self, task_name: str, filename: str) -> str:
        return f"tasks/{task_name}/logs/{filename}"

    def put_comms(self, task_name: str, filename: str, content: str, *, origin: str = "cloud") -> None:
        self._s3.put_object(
            Bucket=self._bucket,
            Key=self._comms_key(task_name, filename),
            Body=content.encode("utf-8"),
            Metadata={"origin": origin},
        )

    def get_comms(self, task_name: str, filename: str) -> str | None:
        try:
            resp = self._s3.get_object(Bucket=self._bucket, Key=self._comms_key(task_name, filename))
            return resp["Body"].read().decode("utf-8")
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            raise

    def delete_comms(self, task_name: str, filename: str) -> None:
        self._s3.delete_object(Bucket=self._bucket, Key=self._comms_key(task_name, filename))

    def list_comms_keys(self, task_name: str) -> list[str]:
        prefix = f"tasks/{task_name}/comms/"
        keys: list[str] = []
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                keys.append(key[len(prefix) :])
        return keys

    def _stream_meta_sk(self, kind: str, stream_id: str) -> str:
        return f"STREAMMETA#{kind}#{stream_id}"

    def _stream_chunk_prefix(self, kind: str, stream_id: str) -> str:
        return f"STREAM#{kind}#{stream_id}#"

    def get_stream_size(self, task_name: str, kind: str, stream_id: str) -> int:
        resp = self._table.get_item(
            Key={"pk": f"TASK#{task_name}", "sk": self._stream_meta_sk(kind, stream_id)}
        )
        item = resp.get("Item")
        if not item:
            return 0
        return int(item.get("total_bytes", 0))

    def append_stream(self, task_name: str, kind: str, stream_id: str, chunk: bytes) -> int:
        if not chunk:
            return self.get_stream_size(task_name, kind, stream_id)
        offset = self.get_stream_size(task_name, kind, stream_id)
        remaining = chunk
        pk = f"TASK#{task_name}"
        while remaining:
            piece = remaining[:STREAM_CHUNK_MAX_BYTES]
            remaining = remaining[STREAM_CHUNK_MAX_BYTES:]
            chunk_sk = f"{self._stream_chunk_prefix(kind, stream_id)}{offset:012d}"
            self._table.put_item(
                Item=_ddb(
                    {
                        "pk": pk,
                        "sk": chunk_sk,
                        "entity": "stream_chunk",
                        "kind": kind,
                        "stream_id": stream_id,
                        "offset": offset,
                        "size": len(piece),
                        "data_b64": base64.b64encode(piece).decode("ascii"),
                    }
                )
            )
            offset += len(piece)
        self._table.put_item(
            Item=_ddb(
                {
                    "pk": pk,
                    "sk": self._stream_meta_sk(kind, stream_id),
                    "entity": "stream_meta",
                    "kind": kind,
                    "stream_id": stream_id,
                    "total_bytes": offset,
                    "updated_at": time.time(),
                }
            )
        )
        return offset

    def read_stream_from_offset(
        self, task_name: str, kind: str, stream_id: str, offset: int
    ) -> tuple[bytes, int]:
        total = self.get_stream_size(task_name, kind, stream_id)
        if offset >= total:
            return b"", total
        prefix = self._stream_chunk_prefix(kind, stream_id)
        resp = self._table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
            ExpressionAttributeValues={":pk": f"TASK#{task_name}", ":pfx": prefix},
        )
        chunks = sorted(resp.get("Items", []), key=lambda item: item["sk"])
        buf = bytearray()
        for item in chunks:
            start = int(item.get("offset", 0))
            data = base64.b64decode(str(item.get("data_b64", "")))
            end = start + len(data)
            if end <= offset:
                continue
            skip = max(0, offset - start)
            buf.extend(data[skip:])
        return bytes(buf), total

    def import_stream_from_bytes(
        self, task_name: str, kind: str, stream_id: str, body: bytes
    ) -> int:
        if self.get_stream_size(task_name, kind, stream_id) > 0:
            return self.get_stream_size(task_name, kind, stream_id)
        if not body:
            return 0
        return self.append_stream(task_name, kind, stream_id, body)

    def append_log(self, task_name: str, filename: str, chunk: bytes) -> int:
        # Live streaming reads DynamoDB chunks only; avoid S3 get+put on every upload.
        return self.append_stream(task_name, "log", filename, chunk)

    def get_log(self, task_name: str, filename: str) -> str:
        data, _ = self.read_stream_from_offset(task_name, "log", filename, 0)
        if data:
            return data.decode("utf-8", errors="replace")
        try:
            resp = self._s3.get_object(Bucket=self._bucket, Key=self._log_key(task_name, filename))
            return resp["Body"].read().decode("utf-8", errors="replace")
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return ""
            raise

    def get_bash_stream(self, task_name: str, filename: str) -> str:
        data, _ = self.read_stream_from_offset(task_name, "bash", filename, 0)
        return data.decode("utf-8", errors="replace")

    def list_log_keys(self, task_name: str) -> list[str]:
        prefix = f"tasks/{task_name}/logs/"
        keys: list[str] = []
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"][len(prefix) :])
        return sorted(keys)

    # --- feed index ---

    def put_feed_item(self, task_name: str, item: FeedItem) -> None:
        sk = f"FEED#{item.created_at:020.6f}#{item.id}"
        self._table.put_item(
            Item=_ddb(
                {
                    "pk": f"TASK#{task_name}",
                    "sk": sk,
                    "entity": "feed",
                    "task_name": task_name,
                    "type": item.type,
                    "feed_id": item.id,
                    "created_at": item.created_at,
                    "deletable": item.deletable,
                    "delete_status": item.delete_status,
                    "origin": item.origin,
                }
            )
        )

    def list_feed_items(self, task_name: str) -> list[FeedItem]:
        resp = self._table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
            ExpressionAttributeValues={":pk": f"TASK#{task_name}", ":pfx": "FEED#"},
        )
        items = [self._feed_from_item(i) for i in resp.get("Items", [])]
        items.sort(key=lambda e: (e.created_at, e.id))
        return items

    def update_feed_item(self, task_name: str, feed_id: str, **fields: Any) -> None:
        items = self.list_feed_items(task_name)
        for fi in items:
            if fi.id == feed_id:
                sk = f"FEED#{fi.created_at:020.6f}#{fi.id}"
                names: dict[str, str] = {}
                parts: list[str] = []
                values: dict[str, Any] = {}
                for i, (k, v) in enumerate(fields.items()):
                    name_key = f"#k{i}"
                    names[name_key] = k
                    parts.append(f"{name_key} = :v{i}")
                    values[f":v{i}"] = v
                self._table.update_item(
                    Key={"pk": f"TASK#{task_name}", "sk": sk},
                    UpdateExpression="SET " + ", ".join(parts),
                    ExpressionAttributeValues=_ddb(values),
                    ExpressionAttributeNames=names,
                )
                return

    def delete_environment(self, environment_id: str) -> None:
        self._table.delete_item(Key={"pk": f"ENV#{environment_id}", "sk": "META"})

    def count_tasks_for_environment(self, environment_id: str) -> int:
        resp = self._table.query(
            IndexName="entity-index",
            KeyConditionExpression="entity = :e",
            ExpressionAttributeValues={":e": "task"},
        )
        return sum(
            1
            for i in resp.get("Items", [])
            if i.get("environment_id") == environment_id
            and i.get("status", "active") in ("active", "pending_unarchive")
        )

    def delete_feed_item(self, task_name: str, feed_id: str) -> None:
        items = self.list_feed_items(task_name)
        for fi in items:
            if fi.id == feed_id:
                sk = f"FEED#{fi.created_at:020.6f}#{fi.id}"
                self._table.delete_item(Key={"pk": f"TASK#{task_name}", "sk": sk})
                return

    def _feed_from_item(self, item: dict) -> FeedItem:
        return FeedItem(
            type=item["type"],
            id=item["feed_id"],
            created_at=float(item["created_at"]),
            deletable=item.get("deletable"),
            delete_status=item.get("delete_status"),
            origin=item.get("origin", "cloud"),
        )

    # --- archives ---

    def put_archive(self, record: ArchiveRecord) -> None:
        self._table.put_item(
            Item={
                "pk": f"ARCHIVE#{record.archived_name}",
                "sk": "META",
                "entity": "archive",
                **record.__dict__,
            }
        )

    def list_archives(self, *, limit: int, offset: int) -> tuple[list[ArchiveRecord], int]:
        resp = self._table.query(
            IndexName="entity-index",
            KeyConditionExpression="entity = :e",
            ExpressionAttributeValues={":e": "archive"},
        )
        all_items = [self._archive_from_item(i) for i in resp.get("Items", [])]
        all_items.sort(key=lambda a: a.archived_at, reverse=True)
        total = len(all_items)
        page = all_items[offset : offset + limit]
        return page, total

    def get_archive(self, archived_name: str) -> ArchiveRecord | None:
        resp = self._table.get_item(Key={"pk": f"ARCHIVE#{archived_name}", "sk": "META"})
        item = resp.get("Item")
        return self._archive_from_item(item) if item else None

    def delete_archive(self, archived_name: str) -> None:
        self._table.delete_item(Key={"pk": f"ARCHIVE#{archived_name}", "sk": "META"})

    def _archive_from_item(self, item: dict) -> ArchiveRecord:
        return ArchiveRecord(
            archived_name=item["archived_name"],
            task_name=item["task_name"],
            source_environment_id=item["source_environment_id"],
            archived_date=item["archived_date"],
            archived_at=item["archived_at"],
            last_modified_at=item["last_modified_at"],
            repo=item.get("repo"),
            branch=item.get("branch"),
            owner=item.get("owner"),
            repo_name=item.get("repo_name"),
        )

    # --- telemetry ---

    def _telemetry_ttl(self) -> int:
        return int(time.time()) + TELEMETRY_RETENTION_SEC

    def _minute_bucket(self, ts: float) -> int:
        return int(ts // TELEMETRY_BUCKET_SEC) * TELEMETRY_BUCKET_SEC

    def _float_val(self, value: Any) -> float:
        if isinstance(value, Decimal):
            return float(value)
        return float(value or 0)

    def append_env_error(
        self,
        environment_id: str,
        *,
        ts: float,
        level: str,
        category: str,
        message: str,
        task_name: str | None = None,
        detail: str | None = None,
    ) -> None:
        err_id = f"{int(ts * 1000):013d}"
        item = {
            "pk": f"ENV#{environment_id}",
            "sk": f"ERR#{err_id}",
            "entity": "telemetry_err",
            "ts": _ddb(ts),
            "level": level,
            "category": category,
            "message": message,
            "ttl": self._telemetry_ttl(),
        }
        if task_name:
            item["task_name"] = task_name
        if detail:
            item["detail"] = detail[:4000]
        self._table.put_item(Item=_ddb(item))

    def ingest_telemetry(self, environment_id: str, payload: dict) -> None:
        ts = float(payload.get("ts") or time.time())
        self.heartbeat(environment_id)
        env_metrics = payload.get("env_metrics") or {}
        bucket = self._minute_bucket(ts)
        env_bucket = {
            "pk": f"ENV#{environment_id}",
            "sk": f"TS#{bucket:010d}",
            "entity": "telemetry_env",
            "bucket_ts": bucket,
            "sample_ts": _ddb(ts),
            "metrics": _ddb(env_metrics),
            "ttl": self._telemetry_ttl(),
        }
        self._table.put_item(Item=env_bucket)
        snapshot = {
            "pk": f"ENV#{environment_id}",
            "sk": "SNAP",
            "entity": "telemetry_snap",
            "sample_ts": _ddb(ts),
            "env_metrics": _ddb(env_metrics),
            "task_metrics": [],
        }
        task_snapshots: list[dict] = []
        for raw_task in payload.get("task_metrics") or []:
            if not isinstance(raw_task, dict):
                continue
            task_name = str(raw_task.get("task_name") or "").strip()
            if not task_name:
                continue
            task = self.get_task(task_name)
            enriched = dict(raw_task)
            if task and task.environment_id == environment_id:
                enriched["comms_epoch_lag"] = max(
                    0, int(task.comms_cloud_epoch or 0) - int(task.worker_comms_epoch or 0)
                )
                enriched["sync_health"] = task.sync_health
                active = task.active_command
                enriched["active_command"] = bool(active and active.get("started"))
                dwell: dict[str, float | None] = {}
                now = ts
                if active:
                    claimed_at = active.get("claimed_at")
                    started_at = active.get("started_at")
                    if claimed_at:
                        dwell["claimed_sec"] = round(now - float(claimed_at), 1)
                    if started_at:
                        dwell["started_sec"] = round(now - float(started_at), 1)
                enriched["phase_dwell"] = dwell
            task_bucket = {
                "pk": f"ENV#{environment_id}",
                "sk": f"TASKTS#{task_name}#{bucket:010d}",
                "entity": "telemetry_task",
                "task_name": task_name,
                "bucket_ts": bucket,
                "sample_ts": _ddb(ts),
                "metrics": _ddb(enriched),
                "ttl": self._telemetry_ttl(),
            }
            self._table.put_item(Item=task_bucket)
            self._table.put_item(
                Item=_ddb(
                    {
                        "pk": f"ENV#{environment_id}",
                        "sk": f"TASKACT#{task_name}",
                        "entity": "telemetry_task_act",
                        "task_name": task_name,
                        "last_activity": _ddb(ts),
                        "ttl": self._telemetry_ttl(),
                    }
                )
            )
            task_snapshots.append(_ddb(enriched))
        snapshot["task_metrics"] = task_snapshots
        self._table.put_item(Item=_ddb(snapshot))
        for raw_err in payload.get("errors") or []:
            if not isinstance(raw_err, dict):
                continue
            message = str(raw_err.get("message") or "").strip()
            if not message:
                continue
            self.append_env_error(
                environment_id,
                ts=float(raw_err.get("ts") or ts),
                level=str(raw_err.get("level") or "error"),
                category=str(raw_err.get("category") or "worker"),
                message=message,
                task_name=str(raw_err.get("task_name") or "").strip() or None,
                detail=str(raw_err.get("detail") or "").strip() or None,
            )

    def get_telemetry_snapshot(self, environment_id: str) -> dict | None:
        resp = self._table.get_item(Key={"pk": f"ENV#{environment_id}", "sk": "SNAP"})
        item = resp.get("Item")
        if not item:
            return None
        return {
            "sample_ts": self._float_val(item.get("sample_ts")),
            "env_metrics": item.get("env_metrics") or {},
            "task_metrics": item.get("task_metrics") or [],
        }

    def query_env_metrics(self, environment_id: str, since: float) -> list[dict]:
        since_bucket = self._minute_bucket(since)
        resp = self._table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :lo AND :hi",
            ExpressionAttributeValues={
                ":pk": f"ENV#{environment_id}",
                ":lo": f"TS#{since_bucket:010d}",
                ":hi": "TS#~",
            },
        )
        points = []
        for item in resp.get("Items", []):
            if not str(item.get("sk", "")).startswith("TS#"):
                continue
            points.append(
                {
                    "bucket_ts": int(item.get("bucket_ts", 0)),
                    "sample_ts": self._float_val(item.get("sample_ts")),
                    "metrics": item.get("metrics") or {},
                }
            )
        return sorted(points, key=lambda p: p["bucket_ts"])

    def query_task_metrics(self, environment_id: str, task_name: str, since: float) -> list[dict]:
        since_bucket = self._minute_bucket(since)
        resp = self._table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :lo AND :hi",
            ExpressionAttributeValues={
                ":pk": f"ENV#{environment_id}",
                ":lo": f"TASKTS#{task_name}#{since_bucket:010d}",
                ":hi": f"TASKTS#{task_name}#~",
            },
        )
        points = []
        for item in resp.get("Items", []):
            points.append(
                {
                    "bucket_ts": int(item.get("bucket_ts", 0)),
                    "sample_ts": self._float_val(item.get("sample_ts")),
                    "metrics": item.get("metrics") or {},
                }
            )
        return sorted(points, key=lambda p: p["bucket_ts"])

    def query_env_errors(self, environment_id: str, since: float) -> list[dict]:
        resp = self._table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={
                ":pk": f"ENV#{environment_id}",
                ":prefix": "ERR#",
            },
            ScanIndexForward=False,
        )
        errors = []
        for item in resp.get("Items", []):
            ts = self._float_val(item.get("ts"))
            if ts < since:
                continue
            errors.append(
                {
                    "ts": ts,
                    "level": item.get("level", "error"),
                    "category": item.get("category", "worker"),
                    "message": item.get("message", ""),
                    "task_name": item.get("task_name"),
                    "detail": item.get("detail"),
                }
            )
        return sorted(errors, key=lambda e: e["ts"], reverse=True)

    def list_telemetry_tasks(self, environment_id: str, since: float) -> list[str]:
        resp = self._table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={
                ":pk": f"ENV#{environment_id}",
                ":prefix": "TASKACT#",
            },
        )
        names: list[str] = []
        for item in resp.get("Items", []):
            last = self._float_val(item.get("last_activity"))
            if last >= since:
                name = item.get("task_name")
                if name:
                    names.append(str(name))
        return sorted(set(names))


def next_comms_filename(existing: list[str], role: str, *, kind: str | None = None) -> str:
    """Generate next comms filename like local comms module."""
    max_n = 0
    for name in existing:
        if name == "index.txt":
            continue
        try:
            n = int(name.split("-")[0])
            if n > max_n:
                max_n = n
        except ValueError:
            pass
    seq = max_n + 1
    if role == "user" and kind == "bash":
        return f"{seq:03d}-user-bash.md"
    if role == "user":
        return f"{seq:03d}-user.md"
    if role == "agent" and kind == "question":
        return f"{seq:03d}-agent-question.md"
    if role == "agent" and kind == "pr-comments":
        return f"{seq:03d}-agent-pr-comments.md"
    return f"{seq:03d}-agent.md"


def collect_pr_comment_keys(comms_bodies: dict[str, str]) -> set[str]:
    keys: set[str] = set()
    for text in comms_bodies.values():
        for m in re.finditer(
            r"\[//\]:\s*#\s*\(\s*pr_comment_key:\s*([a-z]+:\d+)\s*\)",
            text,
        ):
            keys.add(m.group(1))
    return keys
