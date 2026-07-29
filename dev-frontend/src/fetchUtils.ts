export const DEFAULT_FETCH_TIMEOUT_MS = 30_000
export const DEFAULT_FETCH_RETRIES = 2

export async function fetchWithTimeout(
  url: string,
  init?: RequestInit,
  timeoutMs = DEFAULT_FETCH_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(url, { ...init, signal: controller.signal })
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') {
      throw new Error(`Request timed out after ${timeoutMs / 1000}s`)
    }
    throw e
  } finally {
    clearTimeout(timeoutId)
  }
}

export async function fetchWithRetry(
  url: string,
  init?: RequestInit,
  opts?: { timeoutMs?: number; retries?: number },
): Promise<Response> {
  const retries = opts?.retries ?? DEFAULT_FETCH_RETRIES
  const timeoutMs = opts?.timeoutMs ?? DEFAULT_FETCH_TIMEOUT_MS
  let lastError: unknown
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      return await fetchWithTimeout(url, init, timeoutMs)
    } catch (e) {
      lastError = e
      if (attempt === retries) break
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError))
}
