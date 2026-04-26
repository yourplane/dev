/** Base URL for API requests. Default `/api` uses Vite proxy (single-port dev). Override with VITE_DEV_SERVER_URL to talk to backend directly. */
export const apiBaseUrl = import.meta.env.VITE_DEV_SERVER_URL ?? '/api';

async function request<T>(
  path: string,
  options?: RequestInit & { parseJson?: boolean }
): Promise<T> {
  const { parseJson = true, ...init } = options ?? {};
  const url = `${apiBaseUrl}${path}`;
  let res: Response;
  try {
    res = await fetch(url, {
      headers: { 'Content-Type': 'application/json', ...init.headers },
      ...init,
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    throw new Error(
      `Could not reach dev-server at ${apiBaseUrl}. ${msg === 'Failed to fetch' ? 'Check that the backend is running (and that the Vite proxy target matches).' : msg}`
    );
  }
  const text = await res.text();
  if (!res.ok) {
    let detail = text;
    try {
      const j = JSON.parse(text);
      if (typeof j.detail === 'string') detail = j.detail;
    } catch {
      // use raw text
    }
    throw new Error(detail || `HTTP ${res.status}`);
  }
  if (!parseJson || text === '') return undefined as T;
  return JSON.parse(text) as T;
}

export interface CreateTaskBody {
  title: string;
  repo: string;
  comment?: string | null;
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

export const api = {
  getTasks(): Promise<{ tasks: string[] }> {
    return request('/tasks');
  },

  getRepos(): Promise<Record<string, string>> {
    return request('/repos');
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
      res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      throw new Error(
        `Could not reach dev-server at ${apiBaseUrl}. ${msg === 'Failed to fetch' ? 'Check that the backend is running (and that the Vite proxy target matches).' : msg}`
      );
    }
    if (!res.ok) {
      const text = await res.text();
      let detail = text;
      try {
        const j = JSON.parse(text) as { detail?: string };
        if (typeof j.detail === 'string') detail = j.detail;
      } catch {
        // use raw text
      }
      throw new Error(detail || `HTTP ${res.status}`);
    }
    const reader = res.body?.getReader();
    if (!reader) {
      throw new Error('No response body from create task');
    }
    const decoder = new TextDecoder();
    let buffer = '';
    let result: CreateTaskResponse | null = null;
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
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
      }
      if (done) {
        break;
      }
    }
    if (buffer.trim()) {
      const trimmed = buffer.trim();
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
    }
    if (!result) {
      throw new Error('Task creation finished without a result');
    }
    return result;
  },

  getNewTaskDraft(): Promise<{ title?: string; repo?: string; comment?: string }> {
    return request('/drafts/new-task');
  },

  setNewTaskDraft(data: { title?: string; repo?: string; comment?: string }): Promise<void> {
    return request('/drafts/new-task', {
      method: 'PUT',
      body: JSON.stringify(data),
      parseJson: false,
    });
  },

  async getTaskCommentDraft(taskName: string): Promise<string> {
    const url = `${apiBaseUrl}/tasks/${encodeURIComponent(taskName)}/drafts/comment`;
    const res = await fetch(url);
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
    opts?: { after?: number }
  ): Promise<{
    entries: Array<{ type: string; id: string; created_at: number; deletable?: boolean | null }>;
  }> {
    const params = opts?.after != null ? `?after=${opts.after}` : '';
    return request(`/tasks/${encodeURIComponent(taskName)}/feed${params}`);
  },

  async getTaskLogFile(taskName: string, filename: string): Promise<string> {
    const url = `${apiBaseUrl}/tasks/${encodeURIComponent(taskName)}/logs/${encodeURIComponent(filename)}`;
    const res = await fetch(url);
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
  ): Promise<{ active: boolean; command: string | null; active_log_filename: string | null; command_error: string | null }> {
    return request(`/tasks/${encodeURIComponent(taskName)}/commands`);
  },

  /**
   * Open an EventSource for the active log stream (SSE). Use when a command is running and
   * active_log_filename is set. Close the returned EventSource when done.
   */
  openTaskLogStream(taskName: string): EventSource {
    const url = `${apiBaseUrl}/tasks/${encodeURIComponent(taskName)}/logs/stream`;
    return new EventSource(url);
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
    const res = await fetch(url);
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
    const res = await fetch(url);
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
