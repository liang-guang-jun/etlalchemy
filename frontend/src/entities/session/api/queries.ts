import { useQuery } from '@tanstack/react-query';

import { fetchBootstrapStatus } from './fetchers';

/** Query keys of the session entity. */
export const sessionKeys = {
  all: ['session'] as const,
  bootstrap: () => [...sessionKeys.all, 'bootstrap'] as const,
};

/**
 * Reads the bootstrap status of the deployment.
 *
 * @returns The query result of `GET /iam/bootstrap`.
 */
export function useBootstrapStatus() {
  return useQuery({
    queryKey: sessionKeys.bootstrap(),
    queryFn: fetchBootstrapStatus,
    staleTime: 60_000,
    retry: false,
  });
}
