import axios from 'axios';

import { normalizeError } from './error';

/** Default timeout of an HTTP request, in milliseconds. */
export const API_TIMEOUT_MS = 15_000;

/** Timeout used by the long-running import command. */
export const LONG_RUNNING_TIMEOUT_MS = 0;

type TokenGetter = () => string | null;

let tokenGetter: TokenGetter = () => null;

/**
 * Registers how the HTTP client reads the current bearer token.
 *
 * The shared layer must not import `entities`, so the session store pushes its
 * getter here from the application entry point.
 *
 * @param getter Function returning the current access token, or `null`.
 */
export function bindAccessToken(getter: TokenGetter): void {
  tokenGetter = getter;
}

/**
 * Reads the bearer token the application currently holds.
 *
 * Streaming requests bypass axios (it cannot expose a response stream), so the
 * SSE transport asks here instead of importing the session store.
 *
 * @returns The access token, or `null` when the caller is signed out.
 */
export function readAccessToken(): string | null {
  return tokenGetter();
}

/** Single axios instance used by every request of the application. */
export const client = axios.create({
  baseURL: '/',
  timeout: API_TIMEOUT_MS,
});

client.interceptors.request.use((config) => {
  config.headers.set('X-Request-ID', crypto.randomUUID());
  const token = tokenGetter();
  if (token !== null && token !== '') {
    config.headers.set('Authorization', `Bearer ${token}`);
  }
  return config;
});

client.interceptors.response.use(
  (response) => response,
  (error: unknown) => Promise.reject(normalizeError(error)),
);
