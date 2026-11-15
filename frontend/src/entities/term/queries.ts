import { useQuery } from '@tanstack/react-query';

import { fetchTerm, fetchTerms, fetchTermsForField, fetchTermsForTarget, searchTerms } from './api';

/** Query keys of the term entity. */
export const termKeys = {
  all: ['term'] as const,
  lists: (domainId: string, status?: string) =>
    [...termKeys.all, 'list', domainId, status ?? null] as const,
  detail: (domainId: string, termId: string) =>
    [...termKeys.all, 'detail', domainId, termId] as const,
  forField: (tableId: string, fieldName: string) =>
    [...termKeys.all, 'field', tableId, fieldName] as const,
  forTarget: (targetId: string, targetKind: string, fieldName: string) =>
    [...termKeys.all, 'target', targetKind, targetId, fieldName] as const,
  search: (q: string, domainId?: string) =>
    [...termKeys.all, 'search', q, domainId ?? null] as const,
};

/**
 * Lists the live terms of a domain.
 *
 * @param domainId Id of the domain.
 * @param status Optional lifecycle status filter.
 * @param enabled Whether the request should run.
 * @returns The query result of `GET .../terms`.
 */
export function useTerms(domainId: string, status?: string, enabled = true) {
  return useQuery({
    queryKey: termKeys.lists(domainId, status),
    queryFn: () => fetchTerms(domainId, status),
    enabled: enabled && domainId !== '',
  });
}

/**
 * Reads one term with its aliases and links.
 *
 * @param domainId Id of the domain.
 * @param termId Id of the term, or `undefined` to skip the request.
 * @returns The query result of `GET .../terms/{term_id}`.
 */
export function useTerm(domainId: string, termId: string | undefined) {
  return useQuery({
    queryKey: termKeys.detail(domainId, termId ?? 'unknown'),
    queryFn: () => fetchTerm(domainId, termId ?? ''),
    enabled: termId !== undefined,
  });
}

/**
 * Lists the terms linked to one field.
 *
 * @param tableId Id of the owning table.
 * @param fieldName Name of the field.
 * @returns The query result of `GET /vocabulary/terms-for-field`.
 */
export function useTermsForField(tableId: string, fieldName: string) {
  return useQuery({
    queryKey: termKeys.forField(tableId, fieldName),
    queryFn: () => fetchTermsForField(tableId, fieldName),
    enabled: tableId !== '' && fieldName !== '',
  });
}

/**
 * Lists the terms linked to exactly one catalog object.
 *
 * @param targetId Id of the catalog, schema or table.
 * @param targetKind One of `catalog`, `schema` or `table`.
 * @param fieldName Field name for `field` targets, empty otherwise.
 * @returns The query result of `GET /vocabulary/terms-for-target`.
 */
export function useTermsForTarget(targetId: string, targetKind: string, fieldName = '') {
  return useQuery({
    queryKey: termKeys.forTarget(targetId, targetKind, fieldName),
    queryFn: () => fetchTermsForTarget(targetId, targetKind, fieldName),
    enabled: targetId !== '',
  });
}

/**
 * Searches terms by name, definition or alias.
 *
 * @param q Search text; a single character is enough to start the lookup.
 * @param domainId Optional domain restriction.
 * @returns The query result of `GET /vocabulary/search`.
 */
export function useTermSearch(q: string, domainId?: string) {
  const trimmed = q.trim();
  return useQuery({
    queryKey: termKeys.search(trimmed, domainId),
    queryFn: () => searchTerms(trimmed, domainId),
    enabled: trimmed.length >= 1,
  });
}
