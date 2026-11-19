import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';

import { useSessionStore } from '@/entities/session';
import { normalizeError } from '@/shared/api/error';
import { toast } from '@/shared/ui';

export interface QueryProviderProps {
  children: ReactNode;
}

/** Clears the stored session and sends the user back to the login page. */
function handleUnauthorized(): void {
  useSessionStore.getState().clear();
  if (window.location.pathname !== '/login') {
    window.location.assign('/login');
  }
}

/**
 * Marks a query whose failure is not worth a toast.
 *
 * The display name of an object is decoration: the caller already renders the
 * shortened id while the lookup loads, so the same fallback covers a failure.
 */
export interface SilentQueryMeta {
  silent: boolean;
}

/**
 * Creates the query client with the application defaults.
 *
 * Every request that answers 401 flows through the query cache, so the session
 * is cleared and the user is redirected exactly once for both queries and
 * mutations.
 *
 * @returns The configured query client.
 */
function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: (failureCount, error) => {
          const kind = normalizeError(error).kind;
          if (kind === 'network') {
            return failureCount < 1;
          }
          // A session created a moment ago may not be in the read model yet, so
          // the first requests of a fresh login can answer 401. Retry briefly
          // before treating the token as dead.
          if (kind === 'unauthorized') {
            return failureCount < 3;
          }
          // The read model is eventually consistent: reading a just-created
          // aggregate can answer 404 until its events are projected.
          if (kind === 'not_found') {
            return failureCount < 2;
          }
          return false;
        },
        retryDelay: (failureCount) => Math.min(200 * (failureCount + 1), 800),
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: false,
      },
    },
    queryCache: new QueryCache({
      onError: (error, query) => {
        const normalized = normalizeError(error);
        if (normalized.kind === 'unauthorized') {
          handleUnauthorized();
          return;
        }
        // A query that only decorates the screen keeps its own fallback, so a
        // failure does not pile a toast on top of the content it still shows.
        if ((query.meta as Partial<SilentQueryMeta> | undefined)?.silent === true) {
          return;
        }
        toast.error(normalized.detail);
      },
    }),
  });
}

/**
 * Provides the TanStack Query client to the application.
 *
 * @param props Component props.
 * @returns The query provider element.
 */
export function QueryProvider({ children }: QueryProviderProps) {
  const [queryClient] = useState(createQueryClient);

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
