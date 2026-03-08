const baseUrl = import.meta.env.VITE_DEV_SERVER_URL ?? 'http://localhost:8000';

async function request<T>(
  path: string,
  options?: RequestInit & { parseJson?: boolean }
): Promise<T> {
  const { parseJson = true, ...init } = options ?? {};
  const res = await fetch(`${baseUrl}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init.headers },
    ...init,
  });
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
};
