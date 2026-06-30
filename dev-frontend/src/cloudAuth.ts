/** Cognito authentication for cloud dev mode. */

export interface CloudAuthConfig {
  userPoolId: string;
  clientId: string;
  region?: string;
}

const TOKEN_KEY = 'dev_cloud_id_token';
const CONFIG_KEY = 'dev_cloud_auth_config';

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

export function getIdToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setIdToken(token: string | null): void {
  if (token) sessionStorage.setItem(TOKEN_KEY, token);
  else sessionStorage.removeItem(TOKEN_KEY);
}

export async function signIn(email: string, password: string): Promise<void> {
  const cfg = getCloudAuthConfig();
  if (!cfg) throw new Error('Cloud auth not configured');
  const region = cfg.region ?? 'us-east-1';
  const resp = await fetch(`https://cognito-idp.${region}.amazonaws.com/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-amz-json-1.1',
      'X-Amz-Target': 'AWSCognitoIdentityProviderService.InitiateAuth',
    },
    body: JSON.stringify({
      AuthFlow: 'USER_PASSWORD_AUTH',
      ClientId: cfg.clientId,
      AuthParameters: { USERNAME: email, PASSWORD: password },
    }),
  });
  const data = (await resp.json()) as {
    AuthenticationResult?: { IdToken?: string };
    message?: string;
    __type?: string;
  };
  if (!resp.ok) {
    throw new Error(data.message ?? 'Sign in failed');
  }
  const token = data.AuthenticationResult?.IdToken;
  if (!token) throw new Error('No IdToken in response');
  setIdToken(token);
}

export function signOut(): void {
  setIdToken(null);
}

export function authHeaders(): Record<string, string> {
  const token = getIdToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
