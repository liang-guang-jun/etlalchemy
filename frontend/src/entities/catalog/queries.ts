import { useMemo } from 'react';
import { useQueries, useQuery } from '@tanstack/react-query';

import {
  fetchCatalog,
  fetchCatalogSchemas,
  fetchCatalogs,
  fetchSchemaTables,
  fetchTableColumns,
  searchCatalogObjects,
} from './api';
import type { TreeCatalog, TreeSchema, TreeTable } from './model/object-tree';

/** Query keys of the catalog entity. */
export const catalogKeys = {
  all: ['catalog'] as const,
  lists: () => [...catalogKeys.all, 'list'] as const,
  detail: (catalogId: string) => [...catalogKeys.all, 'detail', catalogId] as const,
  search: (term: string) => [...catalogKeys.all, 'search', term] as const,
  tree: () => [...catalogKeys.all, 'tree'] as const,
  schemas: (catalogId: string) => [...catalogKeys.tree(), 'schemas', catalogId] as const,
  tables: (catalogId: string, schema: string) =>
    [...catalogKeys.tree(), 'tables', catalogId, schema] as const,
  columns: (tableId: string) => [...catalogKeys.tree(), 'columns', tableId] as const,
};

/**
 * Lists every live catalog.
 *
 * @returns The query result of `GET /catalog/catalogs`.
 */
export function useCatalogs() {
  return useQuery({ queryKey: catalogKeys.lists(), queryFn: fetchCatalogs });
}

/**
 * Searches catalogs, schemas, tables and fields by name.
 *
 * @param term Substring to look for; two characters are required.
 * @param enabled Whether the caller wants the request at all.
 * @returns The query result of `GET /catalog/search-objects`.
 */
export function useCatalogObjectSearch(term: string, enabled = true) {
  const trimmed = term.trim();
  return useQuery({
    queryKey: catalogKeys.search(trimmed),
    queryFn: () => searchCatalogObjects(trimmed),
    enabled: enabled && trimmed.length >= 2,
  });
}

/**
 * Reads one catalog.
 *
 * @param catalogId Id of the catalog.
 * @returns The query result of `GET /catalog/catalogs/{catalog_id}`.
 */
export function useCatalog(catalogId: string) {
  return useQuery({
    queryKey: catalogKeys.detail(catalogId),
    queryFn: () => fetchCatalog(catalogId),
  });
}

/**
 * Loads the whole catalog tree: every catalog with its schemas and tables.
 *
 * The tree backs a picker, so the levels are loaded up front — there are only a
 * few dozen tables — which keeps browsing and filtering instant. Columns stay
 * out of it: they are fetched per table, only while a table is expanded.
 *
 * @returns The tree plus its loading state.
 */
export function useCatalogTree() {
  const catalogs = useCatalogs();
  const catalogRows = useMemo(() => catalogs.data ?? [], [catalogs.data]);

  const schemas = useQueries({
    queries: catalogRows.map((catalog) => ({
      queryKey: catalogKeys.schemas(catalog.catalog_id),
      queryFn: () => fetchCatalogSchemas(catalog.catalog_id),
    })),
    combine: (results) => ({
      data: results.map((result) => result.data ?? []),
      isPending: results.some((result) => result.isPending),
      isError: results.some((result) => result.isError),
    }),
  });

  const schemaPairs = useMemo(
    () =>
      catalogRows.flatMap((catalog, index) =>
        (schemas.data[index] ?? []).map((schema) => ({
          catalogId: catalog.catalog_id,
          schema,
        })),
      ),
    [catalogRows, schemas.data],
  );

  const tables = useQueries({
    queries: schemaPairs.map((pair) => ({
      queryKey: catalogKeys.tables(pair.catalogId, pair.schema.name),
      queryFn: () => fetchSchemaTables(pair.catalogId, pair.schema.name),
    })),
    combine: (results) => ({
      data: results.map((result) => result.data ?? []),
      isPending: results.some((result) => result.isPending),
      isError: results.some((result) => result.isError),
    }),
  });

  const tree = useMemo<TreeCatalog[]>(() => {
    const byCatalog = new Map<string, TreeCatalog>();
    for (const catalog of catalogRows) {
      byCatalog.set(catalog.catalog_id, {
        id: catalog.catalog_id,
        name: catalog.name,
        schemas: [],
      });
    }
    schemaPairs.forEach((pair, index) => {
      const schema: TreeSchema = {
        id: pair.schema.schema_id,
        name: pair.schema.name,
        tables: (tables.data[index] ?? []).map<TreeTable>((table) => ({
          id: table.table_id,
          name: table.name,
        })),
      };
      byCatalog.get(pair.catalogId)?.schemas.push(schema);
    });
    return [...byCatalog.values()];
  }, [catalogRows, schemaPairs, tables.data]);

  return {
    tree,
    isPending: catalogs.isPending || schemas.isPending || tables.isPending,
    isError: catalogs.isError || schemas.isError || tables.isError,
    refetch: catalogs.refetch,
  };
}

/**
 * Lists the columns of one table, used while a tree node is expanded.
 *
 * @param tableId Id of the table; an empty string disables the query.
 * @param enabled Whether the caller wants the request at all.
 * @returns The query result of `GET /catalog/tables/{table_id}/fields`.
 */
export function useCatalogTableColumns(tableId: string, enabled = true) {
  return useQuery({
    queryKey: catalogKeys.columns(tableId),
    queryFn: () => fetchTableColumns(tableId),
    enabled: enabled && tableId !== '',
  });
}
