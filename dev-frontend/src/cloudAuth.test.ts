import { describe, expect, it, vi, beforeEach } from 'vitest'
import { completeNewPassword, signIn, signOut } from './cloudAuth'

describe('cloudAuth', () => {
  beforeEach(() => {
    signOut()
    vi.restoreAllMocks()
    vi.stubEnv('VITE_COGNITO_USER_POOL_ID', 'us-east-1_test')
    vi.stubEnv('VITE_COGNITO_CLIENT_ID', 'client-id')
    vi.stubEnv('VITE_AWS_REGION', 'us-east-1')
  })

  it('signIn stores token on success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        AuthenticationResult: { IdToken: 'tok-abc' },
      }),
    }))
    const result = await signIn('user@example.com', 'password')
    expect(result).toEqual({ type: 'success' })
    expect(sessionStorage.getItem('dev_cloud_id_token')).toBe('tok-abc')
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
        AuthenticationResult: { IdToken: 'tok-new' },
      }),
    }))
    await completeNewPassword('sess-1', 'user@example.com', 'NewPassword123!')
    expect(sessionStorage.getItem('dev_cloud_id_token')).toBe('tok-new')
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
