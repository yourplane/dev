import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api, isSpaIndexHtmlBody } from './api'

const SPA_HTML = `<!DOCTYPE html>
<html lang="en">
  <head><title>Dev – Task management</title></head>
  <body><div id="root"></div></body>
</html>`

describe('isSpaIndexHtmlBody', () => {
  it('detects CloudFront SPA fallback HTML', () => {
    expect(isSpaIndexHtmlBody(SPA_HTML)).toBe(true)
  })

  it('does not flag normal markdown comms', () => {
    expect(isSpaIndexHtmlBody('# hello\nworld\n')).toBe(false)
  })
})

describe('getTaskCommsFile', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.stubEnv('VITE_CLOUD_MODE', 'false')
  })

  it('rejects SPA index.html bodies returned with HTTP 200', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        text: async () => SPA_HTML,
      }),
    )

    await expect(api.getTaskCommsFile('task-a', '001-user-bash.md')).rejects.toThrow(
      'Resource not found',
    )
  })

  it('returns normal comms text', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        text: async () => 'echo test\n',
      }),
    )

    await expect(api.getTaskCommsFile('task-a', '001-user-bash.md')).resolves.toBe('echo test\n')
  })
})
