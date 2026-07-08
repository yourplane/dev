import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient, GetCommand, QueryCommand } from "@aws-sdk/lib-dynamodb";

const TABLE = process.env.DEV_CLOUD_TABLE || "dev-cloud";
const STREAM_MAX_DURATION_MS = 165_000;
const HEARTBEAT_INTERVAL_MS = 1000;
const POLL_MS = 250;

const ddb = DynamoDBDocumentClient.from(new DynamoDBClient({}));

function sseEvent(type, data) {
  const payload = typeof data === "string" ? data : JSON.stringify(data);
  const lines = [];
  if (type) lines.push(`event: ${type}`);
  for (const line of payload.split("\n")) {
    lines.push(`data: ${line}`);
  }
  lines.push("", "");
  return lines.join("\n");
}

function streamMetaSk(kind, streamId) {
  return `STREAMMETA#${kind}#${streamId}`;
}

function streamChunkPrefix(kind, streamId) {
  return `STREAM#${kind}#${streamId}#`;
}

async function getStreamSize(taskName, kind, streamId) {
  const resp = await ddb.send(
    new GetCommand({
      TableName: TABLE,
      Key: { pk: `TASK#${taskName}`, sk: streamMetaSk(kind, streamId) },
    }),
  );
  return resp.Item?.total_bytes ? Number(resp.Item.total_bytes) : 0;
}

async function readStreamFromOffset(taskName, kind, streamId, offset) {
  const total = await getStreamSize(taskName, kind, streamId);
  if (offset >= total) {
    return { text: "", total };
  }
  const resp = await ddb.send(
    new QueryCommand({
      TableName: TABLE,
      KeyConditionExpression: "pk = :pk AND begins_with(sk, :pfx)",
      ExpressionAttributeValues: {
        ":pk": `TASK#${taskName}`,
        ":pfx": streamChunkPrefix(kind, streamId),
      },
    }),
  );
  const chunks = (resp.Items || []).sort((a, b) => String(a.sk).localeCompare(String(b.sk)));
  const parts = [];
  for (const item of chunks) {
    const start = Number(item.offset || 0);
    const data = Buffer.from(String(item.data_b64 || ""), "base64");
    const end = start + data.length;
    if (end <= offset) continue;
    const skip = Math.max(0, offset - start);
    parts.push(data.subarray(skip));
  }
  return {
    text: Buffer.concat(parts).toString("utf-8"),
    total,
  };
}

async function getTask(taskName) {
  const resp = await ddb.send(
    new GetCommand({
      TableName: TABLE,
      Key: { pk: `TASK#${taskName}`, sk: "META" },
    }),
  );
  return resp.Item;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseTaskName(path) {
  const m = String(path || "").match(/^\/tasks\/([^/]+)\/stream$/);
  return m ? decodeURIComponent(m[1]) : null;
}

export const handler = awslambda.streamifyResponse(async (event, responseStream) => {
  const httpStream = awslambda.HttpResponseStream.from(responseStream, {
    statusCode: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Access-Control-Allow-Origin": "*",
      "X-Accel-Buffering": "no",
    },
  });

  const taskName = parseTaskName(event.path);
  if (!taskName) {
    httpStream.write("Not found");
    httpStream.end();
    return;
  }

  const qs = event.queryStringParameters || {};
  let logOffset = Math.max(0, Number.parseInt(qs.log_offset || "0", 10) || 0);
  let bashOffset = Math.max(0, Number.parseInt(qs.bash_offset || "0", 10) || 0);
  let maxDurationMs = STREAM_MAX_DURATION_MS;
  if (qs.stream_duration) {
    const seconds = Number.parseFloat(qs.stream_duration);
    if (!Number.isNaN(seconds)) {
      maxDurationMs = Math.min(STREAM_MAX_DURATION_MS, Math.max(500, seconds * 1000));
    }
  }

  const deadline = Date.now() + maxDurationMs;
  let lastHeartbeat = 0;
  const write = (chunk) => httpStream.write(chunk);

  while (Date.now() < deadline) {
    const now = Date.now();
    if (now - lastHeartbeat >= HEARTBEAT_INTERVAL_MS) {
      write(sseEvent("heartbeat", {}));
      lastHeartbeat = now;
    }

    const task = await getTask(taskName);
    if (!task?.active_command) break;

    const active = task.active_command;
    const logName = active.active_log_filename;
    if (logName) {
      const { text, total } = await readStreamFromOffset(taskName, "log", logName, logOffset);
      if (text) {
        logOffset = total;
        write(sseEvent("log", { chunk: text, offset: logOffset }));
      }
    }

    const bashName = active.active_bash_comms_filename;
    if (bashName) {
      const { text, total } = await readStreamFromOffset(taskName, "bash", bashName, bashOffset);
      if (text) {
        bashOffset = total;
        write(sseEvent("bash", { chunk: text, offset: bashOffset }));
      }
    }

    await sleep(POLL_MS);
  }

  write(sseEvent("reconnect", { log_offset: logOffset, bash_offset: bashOffset }));
  httpStream.end();
});
