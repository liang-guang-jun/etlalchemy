import { useQuery } from '@tanstack/react-query';
import { cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { apiError } from '@/shared/api/error';
import { useToastStore } from '@/shared/ui/toast-store';

import { QueryProvider } from './QueryProvider';

afterEach(() => {
  cleanup();
  useToastStore.setState({ items: [] });
});

/**
 * Runs one query that always fails, optionally marked as decoration.
 *
 * @param props Whether the query opts out of the error toast.
 * @returns Nothing; the query result is not rendered.
 */
function Failing({ silent }: { silent: boolean }) {
  useQuery({
    queryKey: ['failing', silent],
    queryFn: () => Promise.reject(apiError('validation', 'Input should be a valid UUID', 422)),
    meta: silent ? { silent: true } : undefined,
    // The default policy already gives up on a 422; being explicit keeps the
    // assertion independent of the retry rules.
    retry: false,
  });
  return null;
}

describe('QueryProvider error reporting', () => {
  it('reports a failing query as an error toast', async () => {
    render(
      <QueryProvider>
        <Failing silent={false} />
      </QueryProvider>,
    );

    await waitFor(() => {
      expect(useToastStore.getState().items).toHaveLength(1);
    });
    expect(useToastStore.getState().items[0]?.kind).toBe('error');
    expect(useToastStore.getState().items[0]?.message).toBe('Input should be a valid UUID');
  });

  it('keeps a silent query quiet, because the caller renders a fallback', async () => {
    render(
      <QueryProvider>
        <Failing silent />
      </QueryProvider>,
    );

    // Wait for the rejection to reach the cache, then assert nothing was shown.
    await waitFor(() => {
      expect(useToastStore.getState().items).toHaveLength(0);
    });
  });
});
