import { z } from 'zod';

import { client } from '@/shared/api/client';

/** A schema row of the read model. */
export const schemaSchema = z.object({
  schema_id: z.string(),
  catalog_id: z.string(),
  name: z.string(),
  description: z.string(),
});

export type Schema = z.infer<typeof schemaSchema>;

/** Body of `PATCH .../schemas/{schema}`. */
export const schemaPatchSchema = z.object({
  name: z.string().min(1, 'Enter a name').optional(),
  description: z.string().optional(),
});

export type SchemaPatch = z.infer<typeof schemaPatchSchema>;

const schemaCreatedSchema = z.object({ schema_id: z.string() });

/**
 * Lists the schemas of a catalog.
 *
 * @param catalogId Id of the catalog.
 * @returns The schema rows.
 */
export async function fetchSchemas(catalogId: string): Promise<Schema[]> {
  const response = await client.get(`/catalog/catalogs/${catalogId}/schemas`);
  return schemaSchema.array().parse(response.data);
}

/**
 * Reads one schema addressed by name or id.
 *
 * @param catalogId Id of the catalog.
 * @param schema Schema name or id.
 * @returns The schema row.
 */
export async function fetchSchema(catalogId: string, schema: string): Promise<Schema> {
  const response = await client.get(`/catalog/catalogs/${catalogId}/schemas/${schema}`);
  return schemaSchema.parse(response.data);
}

/**
 * Creates a schema in a catalog.
 *
 * @param catalogId Id of the catalog.
 * @param schemaName Name of the new schema.
 * @param description Free-form description.
 * @returns Id of the new schema.
 */
export async function createSchema(
  catalogId: string,
  schemaName: string,
  description: string,
): Promise<string> {
  const response = await client.post(`/catalog/catalogs/${catalogId}/schemas`, null, {
    params: { schema_name: schemaName, description },
  });
  return schemaCreatedSchema.parse(response.data).schema_id;
}

/**
 * Renames a schema and/or changes its description.
 *
 * @param catalogId Id of the catalog.
 * @param schema Schema name or id.
 * @param body Fields to change.
 */
export async function changeSchema(
  catalogId: string,
  schema: string,
  body: SchemaPatch,
): Promise<void> {
  await client.patch(`/catalog/catalogs/${catalogId}/schemas/${schema}`, body);
}

/**
 * Soft-deletes a schema with its tables and fields.
 *
 * @param catalogId Id of the catalog.
 * @param schema Schema name or id.
 */
export async function discardSchema(catalogId: string, schema: string): Promise<void> {
  await client.delete(`/catalog/catalogs/${catalogId}/schemas/${schema}`);
}
