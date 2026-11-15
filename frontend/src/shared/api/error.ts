import axios from 'axios';

/** Machine-readable category of a failed request. */
export type ApiErrorKind =
  'conflict' | 'not_found' | 'unauthorized' | 'forbidden' | 'validation' | 'network' | 'unknown';

/** Normalised error handed to every caller and to the query cache. */
export interface ApiError extends Error {
  kind: ApiErrorKind;
  /** HTTP status, or `0` when the request never reached the server. */
  status: number;
  /** Human readable message, taken from the `detail` field when present. */
  detail: string;
}

const KIND_BY_STATUS: Record<number, ApiErrorKind> = {
  400: 'validation',
  401: 'unauthorized',
  403: 'forbidden',
  404: 'not_found',
  409: 'conflict',
  422: 'validation',
};

const FALLBACK_DETAIL = 'Request failed. Please try again later.';

/**
 * Builds a normalised error.
 *
 * @param kind Category of the failure.
 * @param detail Message shown to the user.
 * @param status HTTP status, or `0` for a transport failure.
 * @returns The error object.
 */
export function apiError(kind: ApiErrorKind, detail: string, status = 0): ApiError {
  const error = new Error(detail) as ApiError;
  error.name = 'ApiError';
  error.kind = kind;
  error.status = status;
  error.detail = detail;
  return error;
}

/**
 * Checks whether a value is an error produced by this module.
 *
 * @param value Value to inspect.
 * @returns `true` when the value is an {@link ApiError}.
 */
export function isApiError(value: unknown): value is ApiError {
  return value instanceof Error && 'kind' in value && 'detail' in value;
}

/**
 * Reads the human readable message out of a failed response body.
 *
 * FastAPI answers either a string `detail` or a list of validation items, so
 * both shapes are unwrapped here.
 *
 * @param data Parsed response body.
 * @returns The message, or the shared fallback when nothing usable is present.
 */
export function extractDetail(data: unknown): string {
  if (typeof data === 'string' && data.trim() !== '') {
    return data;
  }
  if (data !== null && typeof data === 'object') {
    const detail = (data as { detail?: unknown }).detail;
    if (typeof detail === 'string' && detail.trim() !== '') {
      return detail;
    }
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) =>
          item !== null &&
          typeof item === 'object' &&
          typeof (item as { msg?: unknown }).msg === 'string'
            ? (item as { msg: string }).msg
            : null,
        )
        .filter((message): message is string => message !== null);
      if (messages.length > 0) {
        return messages.join('; ');
      }
    }
  }
  return FALLBACK_DETAIL;
}

/**
 * Turns anything thrown by the HTTP layer into an {@link ApiError}.
 *
 * @param error Value thrown by axios or by application code.
 * @returns The normalised error; an {@link ApiError} is returned unchanged.
 */
export function normalizeError(error: unknown): ApiError {
  if (isApiError(error)) {
    return error;
  }
  if (axios.isAxiosError(error)) {
    const status = error.response?.status ?? 0;
    if (status === 0) {
      return apiError('network', 'Cannot reach the server. Is the backend running?');
    }
    return apiError(
      KIND_BY_STATUS[status] ?? 'unknown',
      extractDetail(error.response?.data),
      status,
    );
  }
  if (error instanceof Error) {
    return apiError('unknown', error.message);
  }
  return apiError('unknown', FALLBACK_DETAIL);
}
