import { describe, expect, it, vi, beforeEach } from 'vitest'
import {
  completeNewPassword,
  ensureValidIdToken,
  restoreCloudSession,
  signIn,
  signOut,
} from './cloudAuth'

function futureExp(): string {
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
  const payload = btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600 }))
  return `${header}.${payload}.sig`
}

function pastExp(): string {
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
  const payload = btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) - 3600 }))
  return `${header}.${payload}.sig`
}

describe('cloudAuth', () => {
  beforeEach(() => {
    signOut()
    localStorage.clear()
    sessionStorage.clear()
    vi.restoreAllMocks()
    vi.stubEnv('VITE_CLOUD_MODE', 'true')
    vi.stubEnv('VITE_COGNITO_USER_POOL_ID', 'us-east-1_test')
    vi.stubEnv('VITE_COGNITO_CLIENT_ID', 'client-id')
    vi.stubEnv('VITE_AWS_REGION', 'us-east-1')
  })

  it('signIn stores id and refresh tokens in localStorage', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        AuthenticationResult: { IdToken: 'tok-abc', RefreshToken: 'refresh-xyz' },
      }),
    }))
    const result = await signIn('user@example.com', 'password')
    expect(result).toEqual({ type: 'success' })
    expect(localStorage.getItem('dev_cloud_id_token')).toBe('tok-abc')
    expect(localStorage.getItem('dev_cloud_refresh_token')).toBe('refresh-xyz')
  })

  it('signIn returns new_password_required challenge', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ChallengeName: 'NEW_PASSWORD_REQUIRED',
        Session: 'sess-1',
      }),
    }))
    const result = await signIn('user@example.com', 'temp-pass')
    expect(result).toEqual({
      type: 'new_password_required',
      session: 'sess-1',
      email: 'user@example.com',
    })
  })

  it('completeNewPassword stores token', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        AuthenticationResult: { IdToken: 'tok-new', RefreshToken: 'refresh-new' },
      }),
    }))
    await completeNewPassword('sess-1', 'user@example.com', 'NewPassword123!')
    expect(localStorage.getItem('dev_cloud_id_token')).toBe('tok-new')
    expect(localStorage.getItem('dev_cloud_refresh_token')).toBe('refresh-new')
  })

  it('ensureValidIdToken refreshes expired id token', async () => {
    localStorage.setItem('dev_cloud_id_token', pastExp())
    localStorage.setItem('dev_cloud_refresh_token', 'refresh-xyz')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        AuthenticationResult: { IdToken: 'tok-refreshed' },
      }),
    }))
    const ok = await ensureValidIdToken()
    expect(ok).toBe(true)
    expect(localStorage.getItem('dev_cloud_id_token')).toBe('tok-refreshed')
  })

  it('restoreCloudSession keeps valid token without refresh', async () => {
    localStorage.setItem('dev_cloud_id_token', futureExp())
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const ok = await restoreCloudSession()
    expect(ok).toBe(true)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('signIn surfaces Cognito error message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ message: 'Incorrect username or password.' }),
    }))
    await expect(signIn('user@example.com', 'bad')).rejects.toThrow(
      'Incorrect username or password.',
    )
  })
})
