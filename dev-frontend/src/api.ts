/** Base URL for API requests. Default `/api` uses Vite proxy (single-port dev). Override with VITE_DEV_SERVER_URL to talk to backend directly. */
import { authHeaders, ensureValidIdToken, isCloudMode } from './cloudAuth';

export const apiBaseUrl = import.meta.env.VITE_DEV_SERVER_URL ?? '/api';

function apiErrorMessage(httpStatus: number, detail: string): string {
  if (isCloudMode()) {
    if (httpStatus === 401 || httpStatus === 403) {
      return detail || 'Not authorized. Try signing out and back in.';
    }
    return detail || `Cloud API error (HTTP ${httpStatus})`;
  }
  return `Could not reach dev-server at ${apiBaseUrl}. ${detail}`;
}

async function cloudAuthFetch(url: string, init?: RequestInit): Promise<Response> {
  if (isCloudMode()) await ensureValidIdToken();
  return fetch(url, {
    ...init,
    headers: { ...authHeaders(), ...init?.headers },
  });
}

const TASK_STREAM_MAX_MS = 165_000;
const TASK_STREAM_HEARTBEAT_MISS_MS = 5_000;

export interface TaskStreamCallbacks {
  onLog?: (chunk: string, offset: number) => void;
  onBash?: (chunk: string, offset: number) => void;
}

export interface TaskStreamHandle {
  close: () => void;
}

function parseSseBlock(block: string): { event: string; data: string } {
  let event = 'message';
  const dataLines: string[] = [];
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
  }
  return { event, data: dataLines.join('\n') };
}

export function connectTaskStream(
  taskName: string,
  callbacks: TaskStreamCallbacks,
  initialOffsets?: { log_offset?: number; bash_offset?: number },
): TaskStreamHandle {
  let closed = false;
  let logOffset = initialOffsets?.log_offset ?? 0;
  let bashOffset = initialOffsets?.bash_offset ?? 0;
  let abortController: AbortController | null = null;
  let heartbeatTimer: ReturnType<typeof setInterval> | undefined;
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  let lastHeartbeat = Date.now();

  const clearTimers = () => {
    if (heartbeatTimer) clearInterval(heartbeatTimer);
    heartbeatTimer = undefined;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = undefined;
  };

  const handleEvent = (type: string, data: string) => {
    if (type === 'heartbeat') {
      lastHeartbeat = Date.now();
      return;
    }
    if (type === 'reconnect') {
      try {
        const parsed = JSON.parse(data) as { log_offset?: number; bash_offset?: number };
        if (typeof parsed.log_offset === 'number') logOffset = parsed.log_offset;
        if (typeof parsed.bash_offset === 'number') bashOffset = parsed.bash_offset;
      } catch {
        // keep current offsets
      }
      abortController?.abort();
      return;
    }
    try {
      const parsed = JSON.parse(data) as { chunk?: string; offset?: number };
      if (type === 'log' && parsed.chunk != null) {
        if (typeof parsed.offset === 'number') logOffset = parsed.offset;
        callbacks.onLog?.(parsed.chunk, logOffset);
      } else if (type === 'bash' && parsed.chunk != null) {
        if (typeof parsed.offset === 'number') bashOffset = parsed.offset;
        callbacks.onBash?.(parsed.chunk, bashOffset);
      }
    } catch {
      // ignore malformed events
    }
  };

  const connect = async () => {
    if (closed) return;
    abortController?.abort();
    abortController = new AbortController();
    lastHeartbeat = Date.now();
    const params = new URLSearchParams({
      log_offset: String(logOffset),
      bash_offset: String(bashOffset),
    });
    const url = `${apiBaseUrl}/tasks/${encodeURIComponent(taskName)}/stream?${params}`;
    let res: Response;
    try {
      res = await cloudAuthFetch(url, { signal: abortController.signal });
    } catch {
      if (!closed) setTimeout(() => void connect(), 500);
      return;
    }
    if (!res.ok || !res.body) {
      if (!closed) setTimeout(() => void connect(), 500);
      return;
    }
    reconnectTimer = setTimeout(() => {
      abortController?.abort();
    }, TASK_STREAM_MAX_MS);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx = buffer.indexOf('\n\n');
        while (idx >= 0) {
          const block = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          if (block.trim()) {
            const { event, data } = parseSseBlock(block);
            handleEvent(event, data);
          }
          idx = buffer.indexOf('\n\n');
        }
      }
    } catch {
      // aborted or network error
    }
    if (!closed) setTimeout(() => void connect(), 0);
  };

  heartbeatTimer = setInterval(() => {
    if (Date.now() - lastHeartbeat > TASK_STREAM_HEARTBEAT_MISS_MS) {
      abortController?.abort();
    }
  }, 1000);

  void connect();

  return {
    close: () => {
      closed = true;
      clearTimers();
      abortController?.abort();
    },
  };
}

async function request<T>(
  path: string,
  options?: RequestInit & { parseJson?: boolean }
): Promise<T> {
  const { parseJson = true, ...init } = options ?? {};
  const url = `${apiBaseUrl}${path}`;
  let res: Response;
  try {
    res = await cloudAuthFetch(url, {
      headers: { 'Content-Type': 'application/json', ...init.headers },
      ...init,
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    throw new Error(
      isCloudMode()
        ? (msg === 'Failed to fetch' ? 'Could not reach the cloud API. Check your network connection.' : msg)
        : `Could not reach dev-server at ${apiBaseUrl}. ${msg === 'Failed to fetch' ? 'Check that the backend is running (and that the Vite proxy target matches).' : msg}`
    );
  }
  const text = await res.text();
  if (!res.ok) {
    let detail = text;
    try {
      const j = JSON.parse(text);
      if (typeof j.detail === 'string') detail = j.detail;
      else if (typeof j.message === 'string') detail = j.message;
    } catch {
      // use raw text
    }
    throw new Error(apiErrorMessage(res.status, detail || `HTTP ${res.status}`));
  }
  if (!parseJson || text === '') return undefined as T;
  return JSON.parse(text) as T;
}

export interface CreateTaskBody {
  title: string;
  repo?: string | null;
  comment?: string | null;
  environment_id?: string | null;
}

export interface EnvironmentInfo {
  environment_id: string;
  display_name: string;
  online: boolean;
  last_heartbeat: number;
  registered_at: number;
}

export interface BranchStatusInfo {
  ahead: number;
  behind: number;
}

export interface TaskWorkspaceInfo {
  repo_label: string | null;
  branch_status?: BranchStatusInfo | null;
}

export interface CreateTaskResponse {
  task_name: string;
  task_dir: string;
}

export interface ArchiveTaskResponse {
  archived_to: string;
}

export interface ArchivedTaskEntry {
  archived_name: string;
  task_name: string;
  archived_date: string;
  archived_at: string;
  last_modified_at: string;
}

export interface ListArchiveResponse {
  entries: ArchivedTaskEntry[];
  total: number;
  next_offset: number | null;
}

export interface UnarchiveTaskResponse {
  restored_task_name: string;
}

export interface CopyFromArchiveResponse {
  task_name: string;
  task_dir: string;
}

export type TaskListStatus =
  | 'idle'
  | 'worker_issue'
  | 'syncing'
  | 'running'
  | 'failed'
  | 'waiting_for_answers'
  | 'ready_for_next_step'
  | 'plan_complete'
  | 'implement_complete'
  | 'merge_from_main_complete'
  | 'user_comment'
  | 'pr_comments'
  | 'bash_complete';

export interface TaskListEntry {
  name: string;
  status: TaskListStatus;
}

export const api = {
  getTasks(): Promise<{ tasks: TaskListEntry[] }> {
    return request('/tasks');
  },

  getTaskWorkspace(taskName: string): Promise<TaskWorkspaceInfo> {
    return request(`/tasks/${encodeURIComponent(taskName)}/workspace`);
  },

  getRepos(): Promise<Record<string, string>> {
    return request('/repos');
  },

  getEnvironments(): Promise<{ environments: EnvironmentInfo[] }> {
    return request('/environments');
  },

  updateEnvironment(environmentId: string, displayName: string): Promise<void> {
    return request(`/environments/${encodeURIComponent(environmentId)}`, {
      method: 'PUT',
      body: JSON.stringify({ display_name: displayName }),
      parseJson: false,
    });
  },

  deleteEnvironment(environmentId: string): Promise<void> {
    return request(`/environments/${encodeURIComponent(environmentId)}`, {
      method: 'DELETE',
      parseJson: false,
    });
  },

  getBots(): Promise<{ bots: Array<{ org: string; secret: string }> }> {
    return request('/config/bots');
  },

  setBots(bots: Array<{ org: string; secret: string }>): Promise<void> {
    return request('/config/bots', {
      method: 'PUT',
      body: JSON.stringify({ bots }),
      parseJson: false,
    });
  },

  addRepo(name: string, url: string): Promise<Record<string, string>> {
    return request('/repos', {
      method: 'POST',
      body: JSON.stringify({ name: name.trim(), url: url.trim() }),
    });
  },

  removeRepo(shorthand: string): Promise<void> {
    return request(`/repos/${encodeURIComponent(shorthand)}`, {
      method: 'DELETE',
      parseJson: false,
    });
  },

  async createTask(
    body: CreateTaskBody,
    onProgress?: (message: string) => void,
  ): Promise<CreateTaskResponse> {
    const url = `${apiBaseUrl}/tasks`;
    let res: Response;
    try {
      res = await cloudAuthFetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      throw new Error(
        isCloudMode()
          ? (msg === 'Failed to fetch' ? 'Could not reach the cloud API. Check your network connection.' : msg)
          : `Could not reach dev-server at ${apiBaseUrl}. ${msg === 'Failed to fetch' ? 'Check that the backend is running (and that the Vite proxy target matches).' : msg}`
      );
    }
    if (!res.ok) {
      const text = await res.text();
      let detail = text;
      try {
        const j = JSON.parse(text) as { detail?: string; message?: string };
        if (typeof j.detail === 'string') detail = j.detail;
        else if (typeof j.message === 'string') detail = j.message;
      } catch {
        // use raw text
      }
      throw new Error(apiErrorMessage(res.status, detail || `HTTP ${res.status}`));
    }
    const reader = res.body?.getReader();
    if (!reader) {
      throw new Error('No response body from create task');
    }
    const decoder = new TextDecoder();
    let buffer = '';
    let result: CreateTaskResponse | null = null;
    const handleLine = (trimmed: string) => {
      const obj = JSON.parse(trimmed) as {
        type: string;
        message?: string;
        task_name?: string;
        task_dir?: string;
        detail?: string;
      };
      if (obj.type === 'progress' && typeof obj.message === 'string') {
        onProgress?.(obj.message);
      }
      if (obj.type === 'complete' && typeof obj.task_name === 'string' && typeof obj.task_dir === 'string') {
        result = { task_name: obj.task_name, task_dir: obj.task_dir };
      }
      if (obj.type === 'error' && typeof obj.detail === 'string') {
        throw new Error(obj.detail);
      }
    };
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';
      for (const line of lines) {
        const trimmed = line.trim();
        if (trimmed) handleLine(trimmed);
      }
      if (done) {
        break;
      }
    }
    if (buffer.trim()) {
      handleLine(buffer.trim());
    }
    if (!result) {
      throw new Error('Task creation finished without a result');
    }
    return result;
  },

  getNewTaskDraft(): Promise<{
    title?: string;
    repo?: string | null;
    comment?: string;
  }> {
    return request('/drafts/new-task');
  },

  setNewTaskDraft(data: {
    title?: string;
    repo?: string | null;
    comment?: string;
  }): Promise<void> {
    return request('/drafts/new-task', {
      method: 'PUT',
      body: JSON.stringify(data),
      parseJson: false,
    });
  },

  async getTaskCommentDraft(taskName: string): Promise<string> {
    const url = `${apiBaseUrl}/tasks/${encodeURIComponent(taskName)}/drafts/comment`;
    const res = await cloudAuthFetch(url);
    if (!res.ok) {
      const text = await res.text();
      let detail = text;
      try {
        const j = JSON.parse(text);
        if (typeof j.detail === 'string') detail = j.detail;
      } catch {
        // use raw text
      }
      throw new Error(detail || `HTTP ${res.status}`);
    }
    return res.text();
  },

  setTaskCommentDraft(taskName: string, content: string): Promise<void> {
    return request(`/tasks/${encodeURIComponent(taskName)}/drafts/comment`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
      parseJson: false,
    });
  },

  async getTaskBashDraft(taskName: string): Promise<string> {
    const url = `${apiBaseUrl}/tasks/${encodeURIComponent(taskName)}/drafts/bash`;
    const res = await cloudAuthFetch(url);
    if (!res.ok) {
      const text = await res.text();
      let detail = text;
      try {
        const j = JSON.parse(text);
        if (typeof j.detail === 'string') detail = j.detail;
      } catch {
        // use raw text
      }
      throw new Error(detail || `HTTP ${res.status}`);
    }
    return res.text();
  },

  setTaskBashDraft(taskName: string, content: string): Promise<void> {
    return request(`/tasks/${encodeURIComponent(taskName)}/drafts/bash`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
      parseJson: false,
    });
  },

  getQuestionAnswersDraft(
    taskName: string,
    commsFilename: string,
  ): Promise<{
    selections: Record<string, string>
    freeText: Record<string, string>
    expandedFreeText: Record<string, boolean>
    editing?: boolean
  }> {
    return request(
      `/tasks/${encodeURIComponent(taskName)}/drafts/question-answers/${encodeURIComponent(commsFilename)}`,
    );
  },

  setQuestionAnswersDraft(
    taskName: string,
    commsFilename: string,
    data: {
      selections: Record<string, string>
      freeText: Record<string, string>
      expandedFreeText: Record<string, boolean>
      editing?: boolean
    },
  ): Promise<void> {
    return request(
      `/tasks/${encodeURIComponent(taskName)}/drafts/question-answers/${encodeURIComponent(commsFilename)}`,
      {
        method: 'PUT',
        body: JSON.stringify(data),
        parseJson: false,
      },
    );
  },

  postQuestionAnswers(
    taskName: string,
    body: {
      source: string
      answers: Array<{ id: string; text: string; selected: string; free_text: string }>
    },
  ): Promise<{ filename: string }> {
    return request(`/tasks/${encodeURIComponent(taskName)}/comms/question-answers`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },

  archiveTask(taskName: string): Promise<ArchiveTaskResponse> {
    return request(`/tasks/${encodeURIComponent(taskName)}/archive`, {
      method: 'POST',
      parseJson: true,
    });
  },

  getArchive(opts?: { limit?: number; offset?: number }): Promise<ListArchiveResponse> {
    const params = new URLSearchParams();
    if (opts?.limit != null) params.set('limit', String(opts.limit));
    if (opts?.offset != null) params.set('offset', String(opts.offset));
    const suffix = params.size > 0 ? `?${params.toString()}` : '';
    return request(`/archive${suffix}`);
  },

  unarchiveTask(archivedName: string): Promise<UnarchiveTaskResponse> {
    return request(`/archive/${encodeURIComponent(archivedName)}/unarchive`, {
      method: 'POST',
    });
  },

  copyFromArchive(
    archivedName: string,
    taskName?: string
  ): Promise<CopyFromArchiveResponse> {
    return request(`/archive/${encodeURIComponent(archivedName)}/copy`, {
      method: 'POST',
      body: taskName ? JSON.stringify({ task_name: taskName }) : '{}',
    });
  },

  getTaskCommsList(taskName: string): Promise<{ files: string[] }> {
    return request(`/tasks/${encodeURIComponent(taskName)}/comms`);
  },

  deleteCommsFile(taskName: string, filename: string): Promise<void> {
    return request(`/tasks/${encodeURIComponent(taskName)}/comms/${encodeURIComponent(filename)}`, {
      method: 'DELETE',
      parseJson: false,
    });
  },

  getTaskFeed(
    taskName: string,
    opts?: {
      after?: number
      limit?: number
      before?: { created_at: number; id: string }
    }
  ): Promise<{
    entries: Array<{ type: string; id: string; created_at: number; deletable?: boolean | null }>
    total?: number | null
    has_older?: boolean | null
    oldest_cursor?: { created_at: number; id: string } | null
  }> {
    const params = new URLSearchParams()
    if (opts?.after != null) params.set('after', String(opts.after))
    if (opts?.limit != null) params.set('limit', String(opts.limit))
    if (opts?.before) {
      params.set('before_created_at', String(opts.before.created_at))
      params.set('before_id', opts.before.id)
    }
    const suffix = params.size > 0 ? `?${params.toString()}` : ''
    return request(`/tasks/${encodeURIComponent(taskName)}/feed${suffix}`)
  },

  getTaskFeedDeletable(taskName: string): Promise<Record<string, boolean>> {
    return request(`/tasks/${encodeURIComponent(taskName)}/feed/deletable`)
  },

  async getTaskLogFile(taskName: string, filename: string): Promise<string> {
    const url = `${apiBaseUrl}/tasks/${encodeURIComponent(taskName)}/logs/${encodeURIComponent(filename)}`;
    const res = await cloudAuthFetch(url);
    if (!res.ok) {
      const text = await res.text();
      let detail = text;
      try {
        const j = JSON.parse(text);
        if (typeof j.detail === 'string') detail = j.detail;
      } catch {
        // use raw text
      }
      throw new Error(detail || `HTTP ${res.status}`);
    }
    return res.text();
  },

  postTaskComms(taskName: string, content: string): Promise<{ filename: string }> {
    return request(`/tasks/${encodeURIComponent(taskName)}/comms`, {
      method: 'POST',
      body: JSON.stringify({ content }),
    });
  },

  getTaskCommandStatus(
    taskName: string
  ): Promise<{
    active: boolean;
    command: string | null;
    active_log_filename: string | null;
    active_bash_comms_filename: string | null;
    command_error: string | null;
    create_progress?: string[];
    queued?: boolean;
    cancelling?: boolean;
    pending_state?: 'syncing' | 'worker_offline' | null;
    sync_health?: 'unhealthy' | null;
  }> {
    return request(`/tasks/${encodeURIComponent(taskName)}/commands`);
  },

  /**
   * Connect to the multiplexed task SSE stream (agent log + bash). Uses fetch + ReadableStream
   * so Authorization headers work in cloud mode. Call close() when done.
   */
  connectTaskStream(
    taskName: string,
    callbacks: TaskStreamCallbacks,
    initialOffsets?: { log_offset?: number; bash_offset?: number },
  ): TaskStreamHandle {
    return connectTaskStream(taskName, callbacks, initialOffsets);
  },

  startTaskCommand(
    taskName: string,
    command: string,
    prompt?: string
  ): Promise<{ command: string; status: string }> {
    const body = prompt != null ? { command, prompt } : { command }
    return request(`/tasks/${encodeURIComponent(taskName)}/commands`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
  },

  cancelTaskCommand(taskName: string): Promise<void> {
    return request(`/tasks/${encodeURIComponent(taskName)}/commands/cancel`, {
      method: 'POST',
      parseJson: false,
    });
  },

  createTaskPr(taskName: string): Promise<{ pr_url: string }> {
    return request(`/tasks/${encodeURIComponent(taskName)}/create-pr`, {
      method: 'POST',
    });
  },

  getTaskPr(taskName: string): Promise<{ pr_url: string | null }> {
    return request(`/tasks/${encodeURIComponent(taskName)}/pr`);
  },

  pullTaskPrComments(taskName: string): Promise<{ pr_url: string; new_comments_count: number; comms_filename: string | null }> {
    return request(`/tasks/${encodeURIComponent(taskName)}/pull-pr-comments`, {
      method: 'POST',
    });
  },

  async getTaskCommsFile(taskName: string, filename: string): Promise<string> {
    const url = `${apiBaseUrl}/tasks/${encodeURIComponent(taskName)}/comms/${encodeURIComponent(filename)}`;
    const res = await cloudAuthFetch(url);
    if (!res.ok) {
      const text = await res.text();
      let detail = text;
      try {
        const j = JSON.parse(text);
        if (typeof j.detail === 'string') detail = j.detail;
      } catch {
        // use raw text
      }
      throw new Error(detail || `HTTP ${res.status}`);
    }
    return res.text();
  },

  /**
   * Download all task comms (no agent logs) as a zip file. Triggers a browser download.
   */
  async downloadTaskCommsZip(taskName: string): Promise<void> {
    const url = `${apiBaseUrl}/tasks/${encodeURIComponent(taskName)}/comms/download`;
    const res = await cloudAuthFetch(url);
    if (!res.ok) {
      const text = await res.text();
      let detail = text;
      try {
        const j = JSON.parse(text);
        if (typeof j.detail === 'string') detail = j.detail;
      } catch {
        // use raw text
      }
      throw new Error(detail || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const disposition = res.headers.get('Content-Disposition');
    const match = disposition?.match(/filename="?([^";\n]+)"?/);
    const filename = match?.[1]?.trim() ?? `${taskName}-comms.zip`;
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  },
};
