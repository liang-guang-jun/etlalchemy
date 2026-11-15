/** Path of a catalog page. */
export function catalogPath(catalogId: string): string {
  return `/catalog/${encodeURIComponent(catalogId)}`;
}

/** Path of a schema inside a catalog page. */
export function schemaPath(catalogId: string, schema: string): string {
  return `${catalogPath(catalogId)}/schemas/${encodeURIComponent(schema)}`;
}

/** Path of a table page. */
export function tablePath(catalogId: string, schema: string, table: string): string {
  return `${schemaPath(catalogId, schema)}/tables/${encodeURIComponent(table)}`;
}

/** Path of a column page. */
export function columnPath(
  catalogId: string,
  schema: string,
  table: string,
  column: string,
): string {
  return `${tablePath(catalogId, schema, table)}/columns/${encodeURIComponent(column)}`;
}

/** Location segments addressed by a catalog URL. */
export interface CatalogLocation {
  catalogId?: string;
  schema?: string;
  table?: string;
  column?: string;
}

/**
 * Reads the catalog, schema and table segments of a pathname.
 *
 * @param pathname Current router pathname.
 * @returns The decoded segments, with the missing ones left `undefined`.
 */
export function parseCatalogPath(pathname: string): CatalogLocation {
  const segments = pathname.split('/').filter((segment) => segment !== '');
  if (segments[0] !== 'catalog') {
    return {};
  }
  const decode = (value: string | undefined) =>
    value === undefined ? undefined : decodeURIComponent(value);

  return {
    catalogId: decode(segments[1]),
    schema: segments[2] === 'schemas' ? decode(segments[3]) : undefined,
    table: segments[4] === 'tables' ? decode(segments[5]) : undefined,
    column: segments[6] === 'columns' ? decode(segments[7]) : undefined,
  };
}
