import type { CatalogObjectSearchResult } from '../api';

/** One column node of the tree. */
export interface TreeColumn {
  /** Column name. */
  name: string;
  /** Canonical data type, empty when the search did not report one. */
  data_type: string;
}

/** One table node of the tree. */
export interface TreeTable {
  /** Table id. */
  id: string;
  /** Table name. */
  name: string;
}

/** One schema node of the tree. */
export interface TreeSchema {
  /** Schema id. */
  id: string;
  /** Schema name. */
  name: string;
  /** Tables of the schema. */
  tables: TreeTable[];
}

/** One catalog node of the tree. */
export interface TreeCatalog {
  /** Catalog id. */
  id: string;
  /** Catalog name. */
  name: string;
  /** Schemas of the catalog. */
  schemas: TreeSchema[];
}

/** Level a picked object sits on. */
export type CatalogObjectKind = 'catalog' | 'schema' | 'table' | 'field';

/** One object picked in the catalog tree. */
export interface CatalogObject {
  /** Level the object sits on. */
  kind: CatalogObjectKind;
  /** Id of the catalog, schema or table, or of the owning table for a field. */
  targetId: string;
  /** Column name for a field, empty for every other level. */
  fieldName: string;
  /** Name of the object itself, without its parents. */
  name: string;
  /** Path from the catalog down to the object, e.g. `sales / orders / total`. */
  path: string;
  /** Stable identity of the object, see `objectKey`. */
  key: string;
}

/** Column hits of one table, keyed by the owning table id. */
export type ColumnHits = ReadonlyMap<string, TreeColumn[]>;

/**
 * Builds the identity of a tree node, used for expansion and selection state.
 *
 * @param kind Level of the object.
 * @param targetId Id of the catalog, schema or table, or of the owning table for a field.
 * @param fieldName Column name for a field.
 * @returns The key of the node.
 */
export function objectKey(kind: CatalogObjectKind, targetId: string, fieldName = ''): string {
  return fieldName === '' ? `${kind}:${targetId}` : `${kind}:${targetId}:${fieldName}`;
}

/**
 * Joins the names of a node's ancestors into one path.
 *
 * @param parts Names from the catalog down to the object.
 * @returns The slash separated path.
 */
export function joinPath(...parts: string[]): string {
  return parts.filter((part) => part !== '').join(' / ');
}

/**
 * Groups the field hits of a cross-level search by their table.
 *
 * The search endpoint reports a hit for every field of a table whose schema or
 * table name matched, so the entries are de-duplicated per column name.
 *
 * @param results Hits of `GET /catalog/search-objects`.
 * @returns The columns of every table that has a hit.
 */
export function columnsByTable(results: readonly CatalogObjectSearchResult[]): ColumnHits {
  const hits = new Map<string, TreeColumn[]>();
  for (const result of results) {
    if (result.kind !== 'field') {
      continue;
    }
    const columns = hits.get(result.target_id) ?? [];
    if (!columns.some((column) => column.name === result.field_name)) {
      columns.push({ name: result.field_name, data_type: result.data_type });
    }
    hits.set(result.target_id, columns);
  }
  return hits;
}

/**
 * Filters the tree with the same rules the resource explorer uses.
 *
 * A node survives when it matches itself or contains a match further down, so
 * the path to every hit stays complete; siblings without a hit disappear. A
 * table also survives when one of its columns matched, which the cross-level
 * field search reports through `hits`.
 *
 * @param tree Tree to filter.
 * @param term Search term; it is trimmed and matched case-insensitively.
 * @param hits Column hits per table id, empty when only names are matched.
 * @returns The filtered tree, or the whole tree for an empty term.
 */
export function filterCatalogTree(
  tree: readonly TreeCatalog[],
  term: string,
  hits: ColumnHits = new Map(),
): TreeCatalog[] {
  const needle = term.trim().toLowerCase();
  if (needle === '') {
    return [...tree];
  }
  const matches = (name: string): boolean => name.toLowerCase().includes(needle);

  const catalogs: TreeCatalog[] = [];
  for (const catalog of tree) {
    const schemas: TreeSchema[] = [];
    for (const schema of catalog.schemas) {
      const tables = schema.tables.filter((table) => matches(table.name) || hits.has(table.id));
      if (matches(schema.name) || tables.length > 0) {
        schemas.push({ ...schema, tables });
      }
    }
    if (matches(catalog.name) || schemas.length > 0) {
      catalogs.push({ ...catalog, schemas });
    }
  }
  return catalogs;
}

/**
 * Counts the tables the tree currently shows.
 *
 * @param tree Tree to count.
 * @returns Number of tables in the filtered tree.
 */
export function countTables(tree: readonly TreeCatalog[]): number {
  return tree.reduce(
    (total, catalog) =>
      total + catalog.schemas.reduce((sum, schema) => sum + schema.tables.length, 0),
    0,
  );
}
