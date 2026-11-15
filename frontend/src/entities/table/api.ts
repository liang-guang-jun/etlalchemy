import { z } from 'zod';

import { client } from '@/shared/api/client';

/** A table row of the read model. */
export const tableSchema = z.object({
  table_id: z.string(),
  schema_id: z.string(),
  catalog_id: z.string(),
  name: z.string(),
  description: z.string().default(''),
});

export type Table = z.infer<typeof tableSchema>;

/** A table plus the names of the schema and catalog that own it. */
export const tableLocationSchema = z.object({
  table_id: z.string(),
  name: z.string(),
  catalog_id: z.string(),
  schema_id: z.string(),
  schema_name: z.string(),
});

export type TableLocation = z.infer<typeof tableLocationSchema>;

/** Body of `PATCH .../tables/{table}`. */
export const tablePatchSchema = z.object({
  name: z.string().min(1, 'Enter a name').optional(),
  description: z.string().optional(),
});

export type TablePatch = z.infer<typeof tablePatchSchema>;

const tableCreatedSchema = z.object({ table_id: z.string() });

/**
 * Lists the tables of a schema.
 *
 * @param catalogId Id of the catalog.
 * @param schema Schema name or id.
 * @returns The table rows.
 */
export async function fetchTables(catalogId: string, schema: string): Promise<Table[]> {
  const response = await client.get(`/catalog/catalogs/${catalogId}/schemas/${schema}/tables`);
  return tableSchema.array().parse(response.data);
}

/**
 * Reads a table and the names of the schema and catalog that own it.
 *
 * Contexts that only keep a `table_id` — the semantic entities, for instance —
 * use this to render a readable `schema.table` path.
 *
 * @param tableId Id of the table.
 * @returns The table location.
 */
export async function fetchTableLocation(tableId: string): Promise<TableLocation> {
  const response = await client.get(`/catalog/tables/${tableId}`);
  return tableLocationSchema.parse(response.data);
}

/**
 * Reads one table addressed by name or id.
 *
 * @param catalogId Id of the catalog.
 * @param schema Schema name or id.
 * @param table Table name or id.
 * @returns The table row.
 */
export async function fetchTable(catalogId: string, schema: string, table: string): Promise<Table> {
  const response = await client.get(
    `/catalog/catalogs/${catalogId}/schemas/${schema}/tables/${table}`,
  );
  return tableSchema.parse(response.data);
}

/**
 * Creates a table in a schema.
 *
 * @param catalogId Id of the catalog.
 * @param schema Schema name or id.
 * @param tableName Name of the new table.
 * @returns Id of the new table.
 */
export async function createTable(
  catalogId: string,
  schema: string,
  tableName: string,
): Promise<string> {
  const response = await client.post(
    `/catalog/catalogs/${catalogId}/schemas/${schema}/tables`,
    null,
    { params: { table_name: tableName } },
  );
  return tableCreatedSchema.parse(response.data).table_id;
}

/**
 * Changes a table name and/or description.
 *
 * @param catalogId Id of the catalog.
 * @param schema Schema name or id.
 * @param table Table name or id.
 * @param patch Fields to change.
 */
export async function changeTable(
  catalogId: string,
  schema: string,
  table: string,
  patch: TablePatch,
): Promise<void> {
  await client.patch(`/catalog/catalogs/${catalogId}/schemas/${schema}/tables/${table}`, patch);
}

/**
 * Soft-deletes a table with its fields.
 *
 * @param catalogId Id of the catalog.
 * @param schema Schema name or id.
 * @param table Table name or id.
 */
export async function discardTable(
  catalogId: string,
  schema: string,
  table: string,
): Promise<void> {
  await client.delete(`/catalog/catalogs/${catalogId}/schemas/${schema}/tables/${table}`);
}
