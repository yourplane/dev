import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { fetchWithRetry, fetchWithTimeout } from './fetchUtils'

describe('fetchUtils', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('fetchWithTimeout rejects when the request exceeds the timeout', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init?: RequestInit) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            reject(Object.assign(new Error('Aborted'), { name: 'AbortError' }))
          })
        }),
      ),
    )

    const promise = fetchWithTimeout('/api/tasks', undefined, 1000)
    const expectation = expect(promise).rejects.toThrow('Request timed out after 1s')
    await vi.advanceTimersByTimeAsync(1000)
    await expectation
  })

  it('fetchWithRetry retries failed requests before succeeding', async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce({ ok: true, text: async () => '{"tasks":[]}' })
    vi.stubGlobal('fetch', fetchMock)

    const res = await fetchWithRetry('/api/tasks', undefined, { timeoutMs: 5000, retries: 1 })
    expect(res.ok).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
