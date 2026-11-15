import { useQuery } from '@tanstack/react-query';

import { fetchSchema, fetchSchemas } from './api';

/** Query keys of the schema entity. */
export const schemaKeys = {
  all: ['schema'] as const,
  lists: (catalogId: string) => [...schemaKeys.all, 'list', catalogId] as const,
  detail: (catalogId: string, schema: string) =>
    [...schemaKeys.all, 'detail', catalogId, schema] as const,
};

/**
 * Lists the schemas of a catalog.
 *
 * @param catalogId Id of the catalog.
 * @param enabled Whether the request should run.
 * @returns The query result of `GET .../schemas`.
 */
export function useSchemas(catalogId: string, enabled = true) {
  return useQuery({
    queryKey: schemaKeys.lists(catalogId),
    queryFn: () => fetchSchemas(catalogId),
    enabled: enabled && catalogId !== '',
  });
}

/**
 * Reads one schema addressed by name or id.
 *
 * @param catalogId Id of the catalog.
 * @param schema Schema name or id, or `undefined` to skip the request.
 * @returns The query result of `GET .../schemas/{schema}`.
 */
export function useSchema(catalogId: string, schema: string | undefined) {
  return useQuery({
    queryKey: schemaKeys.detail(catalogId, schema ?? 'unknown'),
    queryFn: () => fetchSchema(catalogId, schema ?? ''),
    enabled: schema !== undefined,
  });
}
