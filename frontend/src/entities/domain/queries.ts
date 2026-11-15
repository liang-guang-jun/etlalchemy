import { useQuery } from '@tanstack/react-query';

import { fetchDomain, fetchDomains } from './api';

/** Query keys of the domain entity. */
export const domainKeys = {
  all: ['domain'] as const,
  lists: () => [...domainKeys.all, 'list'] as const,
  detail: (domainId: string) => [...domainKeys.all, 'detail', domainId] as const,
};

/**
 * Lists every live domain.
 *
 * @returns The query result of `GET /vocabulary/domains`.
 */
export function useDomains() {
  return useQuery({ queryKey: domainKeys.lists(), queryFn: fetchDomains });
}

/**
 * Reads one domain.
 *
 * @param domainId Id of the domain.
 * @returns The query result of `GET /vocabulary/domains/{domain_id}`.
 */
export function useDomain(domainId: string) {
  return useQuery({
    queryKey: domainKeys.detail(domainId),
    queryFn: () => fetchDomain(domainId),
  });
}
