import { z } from 'zod';

import { client } from '@/shared/api/client';

/** A catalog row of the read model. */
export const catalogSchema = z.object({
  catalog_id: z.string(),
  name: z.string(),
  description: z.string(),
});

export type Catalog = z.infer<typeof catalogSchema>;

/** Body of `PATCH /catalog/catalogs/{catalog_id}`. */
export const catalogPatchSchema = z.object({
  name: z.string().min(1, 'Enter a name').optional(),
  description: z.string().optional(),
});

export type CatalogPatch = z.infer<typeof catalogPatchSchema>;

const catalogCreatedSchema = z.object({ catalog_id: z.string() });

/** One catalog object found by the cross-level name search. */
export const catalogObjectSearchResultSchema = z.object({
  kind: z.enum(['catalog', 'schema', 'table', 'field']),
  target_id: z.string(),
  field_name: z.string(),
  name: z.string(),
  path: z.string(),
  data_type: z.string(),
});

export type CatalogObjectSearchResult = z.infer<typeof catalogObjectSearchResultSchema>;

/**
 * Lists every live catalog.
 *
 * @returns The catalog rows.
 */
export async function fetchCatalogs(): Promise<Catalog[]> {
  const response = await client.get('/catalog/catalogs');
  return catalogSchema.array().parse(response.data);
}

/**
 * Searches catalogs, schemas, tables and fields by name.
 *
 * @param term Substring to look for; matching is case-insensitive.
 * @param catalogId Optional catalog restriction.
 * @returns The matching objects with their paths.
 */
export async function searchCatalogObjects(
  term: string,
  catalogId?: string,
): Promise<CatalogObjectSearchResult[]> {
  const response = await client.get('/catalog/search-objects', {
    params: catalogId === undefined ? { term } : { term, catalog_id: catalogId },
  });
  return catalogObjectSearchResultSchema.array().parse(response.data);
}

/**
 * Reads one catalog.
 *
 * @param catalogId Id of the catalog.
 * @returns The catalog row.
 */
export async function fetchCatalog(catalogId: string): Promise<Catalog> {
  const response = await client.get(`/catalog/catalogs/${catalogId}`);
  return catalogSchema.parse(response.data);
}

/**
 * Creates a catalog. The backend takes the name as query parameters.
 *
 * @param name Name of the new catalog.
 * @param description Free-form description.
 * @returns Id of the new catalog.
 */
export async function createCatalog(name: string, description: string): Promise<string> {
  const response = await client.post('/catalog/catalogs', null, { params: { name, description } });
  return catalogCreatedSchema.parse(response.data).catalog_id;
}

/**
 * Renames a catalog and/or changes its description.
 *
 * @param catalogId Id of the catalog.
 * @param body Fields to change.
 */
export async function changeCatalog(catalogId: string, body: CatalogPatch): Promise<void> {
  await client.patch(`/catalog/catalogs/${catalogId}`, body);
}

/**
 * Soft-deletes a catalog with its schemas, tables and fields.
 *
 * @param catalogId Id of the catalog.
 */
export async function discardCatalog(catalogId: string): Promise<void> {
  await client.delete(`/catalog/catalogs/${catalogId}`);
}

/**
 * One schema node of the catalog tree.
 *
 * The tree is a single read model of the catalog context — it walks catalogs,
 * schemas, tables and columns at once — so it keeps its own narrow shapes
 * instead of the per-level rows the schema, table and field slices expose.
 */
const treeSchemaSchema = z.object({
  schema_id: z.string(),
  name: z.string(),
});

export type TreeSchemaRow = z.infer<typeof treeSchemaSchema>;

/** One table node of the catalog tree. */
const treeTableSchema = z.object({
  table_id: z.string(),
  name: z.string(),
});

export type TreeTableRow = z.infer<typeof treeTableSchema>;

/** One column node of the catalog tree. */
const treeColumnSchema = z.object({
  name: z.string(),
  data_type: z.string(),
});

export type TreeColumnRow = z.infer<typeof treeColumnSchema>;

/**
 * Lists the schemas of a catalog.
 *
 * @param catalogId Id of the catalog.
 * @returns The schema nodes.
 */
export async function fetchCatalogSchemas(catalogId: string): Promise<TreeSchemaRow[]> {
  const response = await client.get(`/catalog/catalogs/${catalogId}/schemas`);
  return treeSchemaSchema.array().parse(response.data);
}

/**
 * Lists the tables of one schema.
 *
 * @param catalogId Id of the catalog.
 * @param schema Schema name or id.
 * @returns The table nodes.
 */
export async function fetchSchemaTables(
  catalogId: string,
  schema: string,
): Promise<TreeTableRow[]> {
  const response = await client.get(`/catalog/catalogs/${catalogId}/schemas/${schema}/tables`);
  return treeTableSchema.array().parse(response.data);
}

/**
 * Lists the columns of one table addressed by its id alone.
 *
 * @param tableId Id of the table.
 * @returns The column nodes.
 */
export async function fetchTableColumns(tableId: string): Promise<TreeColumnRow[]> {
  const response = await client.get(`/catalog/tables/${tableId}/fields`);
  return treeColumnSchema.array().parse(response.data);
}
