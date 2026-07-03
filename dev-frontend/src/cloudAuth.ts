/** Cognito authentication for cloud dev mode. */

export interface CloudAuthConfig {
  userPoolId: string;
  clientId: string;
  region?: string;
}

export type SignInResult =
  | { type: 'success' }
  | { type: 'new_password_required'; session: string; email: string };

const ID_TOKEN_KEY = 'dev_cloud_id_token';
const REFRESH_TOKEN_KEY = 'dev_cloud_refresh_token';
const LEGACY_ID_TOKEN_KEY = 'dev_cloud_id_token';

type CognitoAuthResponse = {
  AuthenticationResult?: { IdToken?: string; RefreshToken?: string };
  ChallengeName?: string;
  Session?: string;
  message?: string;
  __type?: string;
};

export function isCloudMode(): boolean {
  return import.meta.env.VITE_CLOUD_MODE === 'true';
}

export function getCloudAuthConfig(): CloudAuthConfig | null {
  const userPoolId = import.meta.env.VITE_COGNITO_USER_POOL_ID as string | undefined;
  const clientId = import.meta.env.VITE_COGNITO_CLIENT_ID as string | undefined;
  if (!userPoolId || !clientId) return null;
  return {
    userPoolId,
    clientId,
    region: (import.meta.env.VITE_AWS_REGION as string | undefined) ?? 'us-east-1',
  };
}

function migrateFromSessionStorage(): void {
  const legacy = sessionStorage.getItem(LEGACY_ID_TOKEN_KEY);
  if (legacy && !localStorage.getItem(ID_TOKEN_KEY)) {
    localStorage.setItem(ID_TOKEN_KEY, legacy);
  }
  sessionStorage.removeItem(LEGACY_ID_TOKEN_KEY);
}

export function getIdToken(): string | null {
  migrateFromSessionStorage();
  return localStorage.getItem(ID_TOKEN_KEY);
}

function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function setIdToken(token: string | null): void {
  if (token) localStorage.setItem(ID_TOKEN_KEY, token);
  else localStorage.removeItem(ID_TOKEN_KEY);
}

function setRefreshToken(token: string | null): void {
  if (token) localStorage.setItem(REFRESH_TOKEN_KEY, token);
  else localStorage.removeItem(REFRESH_TOKEN_KEY);
}

function decodeJwtExp(token: string): number | null {
  try {
    const payload = JSON.parse(atob(token.split('.')[1])) as { exp?: number };
    return typeof payload.exp === 'number' ? payload.exp : null;
  } catch {
    return null;
  }
}

function isTokenExpired(token: string, skewSec = 60): boolean {
  const exp = decodeJwtExp(token);
  if (!exp) return true;
  return Date.now() / 1000 >= exp - skewSec;
}

let refreshPromise: Promise<boolean> | null = null;

async function cognitoRequest<T>(region: string, target: string, body: Record<string, unknown>): Promise<T> {
  const resp = await fetch(`https://cognito-idp.${region}.amazonaws.com/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-amz-json-1.1',
      'X-Amz-Target': target,
    },
    body: JSON.stringify(body),
  });
  const data = (await resp.json()) as T & { message?: string; __type?: string };
  if (!resp.ok) {
    throw new Error(data.message ?? 'Authentication failed');
  }
  return data;
}

function storeTokensFromAuth(data: CognitoAuthResponse): void {
  const token = data.AuthenticationResult?.IdToken;
  if (!token) {
    if (data.ChallengeName) {
      throw new Error(`Unexpected auth challenge: ${data.ChallengeName}`);
    }
    throw new Error('No IdToken in response');
  }
  setIdToken(token);
  const refresh = data.AuthenticationResult?.RefreshToken;
  if (refresh) setRefreshToken(refresh);
}

async function refreshSession(): Promise<boolean> {
  const refreshToken = getRefreshToken();
  const cfg = getCloudAuthConfig();
  if (!refreshToken || !cfg) return false;
  const region = cfg.region ?? 'us-east-1';
  try {
    const data = await cognitoRequest<CognitoAuthResponse>(
      region,
      'AWSCognitoIdentityProviderService.InitiateAuth',
      {
        AuthFlow: 'REFRESH_TOKEN_AUTH',
        ClientId: cfg.clientId,
        AuthParameters: { REFRESH_TOKEN: refreshToken },
      },
    );
    storeTokensFromAuth(data);
    return true;
  } catch {
    signOut();
    return false;
  }
}

export async function ensureValidIdToken(): Promise<boolean> {
  migrateFromSessionStorage();
  const token = getIdToken();
  if (token && !isTokenExpired(token)) return true;
  if (!getRefreshToken()) return false;
  if (!refreshPromise) {
    refreshPromise = refreshSession().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

/** Restore a persisted session on app load (refresh token, valid for 30 days). */
export async function restoreCloudSession(): Promise<boolean> {
  if (!isCloudMode()) return true;
  migrateFromSessionStorage();
  return ensureValidIdToken();
}

export async function signIn(email: string, password: string): Promise<SignInResult> {
  const cfg = getCloudAuthConfig();
  if (!cfg) throw new Error('Cloud auth not configured');
  const region = cfg.region ?? 'us-east-1';
  const data = await cognitoRequest<CognitoAuthResponse>(
    region,
    'AWSCognitoIdentityProviderService.InitiateAuth',
    {
      AuthFlow: 'USER_PASSWORD_AUTH',
      ClientId: cfg.clientId,
      AuthParameters: { USERNAME: email.trim(), PASSWORD: password },
    },
  );

  if (data.ChallengeName === 'NEW_PASSWORD_REQUIRED') {
    if (!data.Session) throw new Error('Password change required but session missing');
    return { type: 'new_password_required', session: data.Session, email: email.trim() };
  }

  storeTokensFromAuth(data);
  return { type: 'success' };
}

export async function completeNewPassword(
  session: string,
  email: string,
  newPassword: string,
): Promise<void> {
  const cfg = getCloudAuthConfig();
  if (!cfg) throw new Error('Cloud auth not configured');
  const region = cfg.region ?? 'us-east-1';
  const data = await cognitoRequest<CognitoAuthResponse>(
    region,
    'AWSCognitoIdentityProviderService.RespondToAuthChallenge',
    {
      ChallengeName: 'NEW_PASSWORD_REQUIRED',
      ClientId: cfg.clientId,
      Session: session,
      ChallengeResponses: {
        USERNAME: email.trim(),
        NEW_PASSWORD: newPassword,
      },
    },
  );
  storeTokensFromAuth(data);
}

export function signOut(): void {
  setIdToken(null);
  setRefreshToken(null);
}

export function authHeaders(): Record<string, string> {
  const token = getIdToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
