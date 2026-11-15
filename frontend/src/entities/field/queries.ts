import { useQuery } from '@tanstack/react-query';

import { fetchFields, fetchFieldsByTable, searchFields } from './api';

/** Query keys of the field entity. */
export const fieldKeys = {
  all: ['field'] as const,
  list: (catalogId: string, schema: string, table: string) =>
    [...fieldKeys.all, 'list', catalogId, schema, table] as const,
  byTable: (tableId: string) => [...fieldKeys.all, 'table', tableId] as const,
  search: (term: string, catalogId?: string) =>
    [...fieldKeys.all, 'search', term, catalogId ?? null] as const,
};

/**
 * Lists the fields of a table.
 *
 * @param catalogId Id of the catalog.
 * @param schema Schema name or id.
 * @param table Table name or id.
 * @param enabled Whether the caller wants the request at all.
 * @returns The query result of `GET .../fields`.
 */
export function useFields(catalogId: string, schema: string, table: string, enabled = true) {
  return useQuery({
    queryKey: fieldKeys.list(catalogId, schema, table),
    queryFn: () => fetchFields(catalogId, schema, table),
    enabled: enabled && catalogId !== '' && schema !== '' && table !== '',
  });
}

/**
 * Lists the fields of one table addressed by its id alone.
 *
 * @param tableId Id of the table; an empty string disables the query.
 * @returns The query result of `GET /catalog/tables/{table_id}/fields`.
 */
export function useTableFields(tableId: string) {
  return useQuery({
    queryKey: fieldKeys.byTable(tableId),
    queryFn: () => fetchFieldsByTable(tableId),
    enabled: tableId !== '',
  });
}

/**
 * Searches fields across the catalog.
 *
 * @param term Substring to look for.
 * @param catalogId Optional catalog restriction.
 * @returns The query result of `GET /catalog/search`.
 */
export function useFieldSearch(term: string, catalogId?: string) {
  const trimmed = term.trim();
  return useQuery({
    queryKey: fieldKeys.search(trimmed, catalogId),
    queryFn: () => searchFields(trimmed, catalogId),
    enabled: trimmed.length >= 2,
  });
}
