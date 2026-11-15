import { describe, expect, it } from 'vitest';
import { AxiosError, AxiosHeaders } from 'axios';

import { apiError, isApiError, normalizeError } from './error';

describe('normalizeError', () => {
  it('maps a 409 response to a conflict with the detail message', () => {
    const error = new AxiosError('conflict', 'ERR_BAD_REQUEST', undefined, undefined, {
      status: 409,
      statusText: 'Conflict',
      data: { detail: 'catalog already exists' },
      headers: {},
      config: { headers: new AxiosHeaders() },
    });

    const normalized = normalizeError(error);

    expect(normalized.kind).toBe('conflict');
    expect(normalized.status).toBe(409);
    expect(normalized.detail).toBe('catalog already exists');
  });

  it('turns a transport failure into a network error', () => {
    const error = new AxiosError('Network Error', 'ERR_NETWORK');

    expect(normalizeError(error).kind).toBe('network');
  });

  it('joins FastAPI validation messages', () => {
    const error = new AxiosError('invalid', 'ERR_BAD_REQUEST', undefined, undefined, {
      status: 422,
      statusText: 'Unprocessable Entity',
      data: { detail: [{ msg: 'name is required' }, { msg: 'name is too long' }] },
      headers: {},
      config: { headers: new AxiosHeaders() },
    });

    const normalized = normalizeError(error);

    expect(normalized.kind).toBe('validation');
    expect(normalized.detail).toBe('name is required; name is too long');
  });

  it('keeps an already normalised error unchanged', () => {
    const original = apiError('forbidden', 'not allowed', 403);

    expect(normalizeError(original)).toBe(original);
    expect(isApiError(original)).toBe(true);
  });

  it('wraps a plain error as unknown', () => {
    const normalized = normalizeError(new Error('boom'));

    expect(normalized.kind).toBe('unknown');
    expect(normalized.detail).toBe('boom');
  });
});
