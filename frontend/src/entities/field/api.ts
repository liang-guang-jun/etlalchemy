import { z } from 'zod';

import { client } from '@/shared/api/client';

/** Canonical base types accepted by the backend. */
export const DATA_TYPES = [
  'boolean',
  'smallint',
  'integer',
  'bigint',
  'float',
  'double',
  'decimal',
  'string',
  'varchar',
  'char',
  'text',
  'date',
  'timestamp',
  'timestamptz',
  'json',
  'binary',
  'uuid',
] as const;

/** Types that carry integer parameters, e.g. `varchar(255)`. */
export const PARAMETERISED_DATA_TYPES = ['decimal', 'varchar', 'char'] as const;

/** One field of a table. */
export const fieldSchema = z.object({
  table_id: z.string(),
  /** Identity of the field, stable across renames; used e.g. as a comment target. */
  field_id: z.string(),
  name: z.string(),
  data_type: z.string(),
  nullable: z.boolean(),
});

export type Field = z.infer<typeof fieldSchema>;

/** One hit of the cross-catalog field search. */
export const fieldSearchResultSchema = z.object({
  catalog_id: z.string(),
  schema_id: z.string(),
  schema_name: z.string(),
  table_id: z.string(),
  table_name: z.string(),
  field_name: z.string(),
  data_type: z.string(),
  nullable: z.boolean(),
});

export type FieldSearchResult = z.infer<typeof fieldSearchResultSchema>;

/**
 * Lists the fields of a table.
 *
 * @param catalogId Id of the catalog.
 * @param schema Schema name or id.
 * @param table Table name or id.
 * @returns The field rows.
 */
export async function fetchFields(
  catalogId: string,
  schema: string,
  table: string,
): Promise<Field[]> {
  const response = await client.get(
    `/catalog/catalogs/${catalogId}/schemas/${schema}/tables/${table}/fields`,
  );
  return fieldSchema.array().parse(response.data);
}

/**
 * Lists the fields of a table addressed by its id alone.
 *
 * Contexts that only store a `table_id` — the semantic entities, for instance —
 * use this instead of walking the catalog/schema path.
 *
 * @param tableId Id of the table.
 * @returns The field rows.
 */
export async function fetchFieldsByTable(tableId: string): Promise<Field[]> {
  const response = await client.get(`/catalog/tables/${tableId}/fields`);
  return fieldSchema.array().parse(response.data);
}

/**
 * Adds a field to a table.
 *
 * @param catalogId Id of the catalog.
 * @param schema Schema name or id.
 * @param table Table name or id.
 * @param fieldName Name of the new field.
 * @param dataType Canonical data type text, e.g. `varchar(255)`.
 * @param nullable Whether the field accepts null.
 */
export async function addField(
  catalogId: string,
  schema: string,
  table: string,
  fieldName: string,
  dataType: string,
  nullable: boolean,
): Promise<void> {
  await client.post(
    `/catalog/catalogs/${catalogId}/schemas/${schema}/tables/${table}/fields`,
    null,
    { params: { field_name: fieldName, data_type: dataType, nullable } },
  );
}

/**
 * Changes the type and/or nullability of a field.
 *
 * @param catalogId Id of the catalog.
 * @param schema Schema name or id.
 * @param table Table name or id.
 * @param fieldName Name of the field.
 * @param body Fields to change.
 */
export async function changeField(
  catalogId: string,
  schema: string,
  table: string,
  fieldName: string,
  body: { data_type?: string; nullable?: boolean },
): Promise<void> {
  await client.patch(
    `/catalog/catalogs/${catalogId}/schemas/${schema}/tables/${table}/fields/${encodeURIComponent(fieldName)}`,
    body,
  );
}

/**
 * Removes a field from a table.
 *
 * @param catalogId Id of the catalog.
 * @param schema Schema name or id.
 * @param table Table name or id.
 * @param fieldName Name of the field.
 */
export async function discardField(
  catalogId: string,
  schema: string,
  table: string,
  fieldName: string,
): Promise<void> {
  await client.delete(
    `/catalog/catalogs/${catalogId}/schemas/${schema}/tables/${table}/fields/${encodeURIComponent(fieldName)}`,
  );
}

/**
 * Renames a field.
 *
 * @param catalogId Id of the catalog.
 * @param schema Schema name or id.
 * @param table Table name or id.
 * @param fieldName Current name of the field.
 * @param newName New name of the field.
 */
export async function renameField(
  catalogId: string,
  schema: string,
  table: string,
  fieldName: string,
  newName: string,
): Promise<void> {
  await client.post(
    `/catalog/catalogs/${catalogId}/schemas/${schema}/tables/${table}/fields/${encodeURIComponent(fieldName)}/rename`,
    { new_name: newName },
  );
}

/**
 * Searches fields across schemas, tables and catalog.
 *
 * @param term Substring to look for.
 * @param catalogId Optional catalog restriction.
 * @returns The matching field rows with their location.
 */
export async function searchFields(term: string, catalogId?: string): Promise<FieldSearchResult[]> {
  const response = await client.get('/catalog/search', {
    params: catalogId === undefined ? { term } : { term, catalog_id: catalogId },
  });
  return fieldSearchResultSchema.array().parse(response.data);
}
