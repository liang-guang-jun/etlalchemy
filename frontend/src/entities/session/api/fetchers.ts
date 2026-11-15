import { client, LONG_RUNNING_TIMEOUT_MS } from '@/shared/api/client';

import {
  bootstrapStatusSchema,
  sessionResponseSchema,
  type ApiKeyLogin,
  type BootstrapStatus,
  type PasswordLogin,
  type SessionResponse,
} from './schema';

/**
 * Authenticates with a login and password.
 *
 * @param body Credentials.
 * @returns The new session, including the bearer token and `refresh_at`.
 */
export async function loginWithPassword(body: PasswordLogin): Promise<SessionResponse> {
  const response = await client.post('/iam/auth/password', body);
  return sessionResponseSchema.parse(response.data);
}

/**
 * Authenticates with an API key.
 *
 * @param body The raw API key.
 * @returns The new session, including the bearer token and `refresh_at`.
 */
export async function loginWithApiKey(body: ApiKeyLogin): Promise<SessionResponse> {
  const response = await client.post('/iam/auth/api-key', body);
  return sessionResponseSchema.parse(response.data);
}

/**
 * Reads the current session behind the bearer token.
 *
 * @returns The current session.
 */
export async function fetchCurrentSession(): Promise<SessionResponse> {
  const response = await client.get('/iam/sessions/current');
  return sessionResponseSchema.parse(response.data);
}

/**
 * Extends the session behind the bearer token.
 *
 * The backend decides the new expiry; `refresh_at` says when to call again.
 *
 * @returns The refreshed session.
 */
export async function refreshSession(): Promise<SessionResponse> {
  const response = await client.post('/iam/auth/refresh', undefined, {
    timeout: LONG_RUNNING_TIMEOUT_MS,
  });
  return sessionResponseSchema.parse(response.data);
}

/** Revokes the session behind the bearer token. */
export async function logoutSession(): Promise<void> {
  await client.post('/iam/auth/logout');
}

/**
 * Reads whether the deployment already has a system administrator.
 *
 * @returns The bootstrap status.
 */
export async function fetchBootstrapStatus(): Promise<BootstrapStatus> {
  const response = await client.get('/iam/bootstrap');
  return bootstrapStatusSchema.parse(response.data);
}
