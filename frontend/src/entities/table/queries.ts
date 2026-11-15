import { useQuery } from '@tanstack/react-query';

import { fetchTable, fetchTableLocation, fetchTables } from './api';

/** Query keys of the table entity. */
export const tableKeys = {
  all: ['table'] as const,
  lists: (catalogId: string, schema: string) =>
    [...tableKeys.all, 'list', catalogId, schema] as const,
  detail: (catalogId: string, schema: string, table: string) =>
    [...tableKeys.all, 'detail', catalogId, schema, table] as const,
  byId: (tableId: string) => [...tableKeys.all, 'by-id', tableId] as const,
};

/**
 * Lists the tables of a schema.
 *
 * @param catalogId Id of the catalog.
 * @param schema Schema name or id.
 * @param enabled Whether the request should run.
 * @returns The query result of `GET .../tables`.
 */
export function useTables(catalogId: string, schema: string, enabled = true) {
  return useQuery({
    queryKey: tableKeys.lists(catalogId, schema),
    queryFn: () => fetchTables(catalogId, schema),
    enabled: enabled && catalogId !== '' && schema !== '',
  });
}

/**
 * Reads a table and the names of the schema and catalog that own it.
 *
 * @param tableId Id of the table; an empty string disables the query.
 * @returns The query result of `GET /catalog/tables/{table_id}`.
 */
export function useTableLocation(tableId: string) {
  return useQuery({
    queryKey: tableKeys.byId(tableId),
    queryFn: () => fetchTableLocation(tableId),
    enabled: tableId !== '',
    staleTime: 5 * 60_000,
  });
}

/**
 * Reads one table addressed by name or id.
 *
 * @param catalogId Id of the catalog.
 * @param schema Schema name or id, or `undefined` to skip the request.
 * @param table Table name or id, or `undefined` to skip the request.
 * @returns The query result of `GET .../tables/{table}`.
 */
export function useTable(catalogId: string, schema: string | undefined, table: string | undefined) {
  return useQuery({
    queryKey: tableKeys.detail(catalogId, schema ?? '', table ?? ''),
    queryFn: () => fetchTable(catalogId, schema ?? '', table ?? ''),
    enabled: schema !== undefined && table !== undefined,
  });
}
