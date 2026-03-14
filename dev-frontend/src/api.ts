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
  task_name?: string | null;
}

export interface CreateTaskResponse {
  task_name: string;
  task_dir: string;
}

export interface ArchiveTaskResponse {
  archived_to: string;
}

export const api = {
  getTasks(): Promise<{ tasks: string[] }> {
    return request('/tasks');
  },

  getRepos(): Promise<Record<string, string>> {
    return request('/repos');
  },

  createTask(body: CreateTaskBody): Promise<CreateTaskResponse> {
    return request('/tasks', {
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

  getTaskCommsList(taskName: string): Promise<{ files: string[] }> {
    return request(`/tasks/${encodeURIComponent(taskName)}/comms`);
  },

  postTaskComms(taskName: string, content: string): Promise<{ filename: string }> {
    return request(`/tasks/${encodeURIComponent(taskName)}/comms`, {
      method: 'POST',
      body: JSON.stringify({ content }),
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
};
