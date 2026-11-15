import { z } from 'zod';

import { client, LONG_RUNNING_TIMEOUT_MS } from '@/shared/api/client';

/** One source connection of the read model. */
export const connectionSchema = z.object({
  connection_id: z.string(),
  name: z.string(),
  kind: z.string(),
  endpoint: z.string(),
  credential_ref: z.string().nullable(),
  has_inline_credential: z.boolean(),
  default_catalog: z.string().nullable(),
  options: z.record(z.string(), z.string()),
});

export type Connection = z.infer<typeof connectionSchema>;

/** Body of `POST /ingestion/connections`. */
export const connectionCreateSchema = z.object({
  name: z.string().min(1, 'Enter a name'),
  kind: z.string().min(1, 'Choose a source kind'),
  endpoint: z.string(),
  credential_ref: z.string().optional(),
  token: z.string().optional(),
  default_catalog: z.string().optional(),
  options: z.record(z.string(), z.string()).optional(),
});

export type ConnectionCreate = z.infer<typeof connectionCreateSchema>;

/** Body of `PATCH /ingestion/connections/{connection_id}`. */
export const connectionPatchSchema = z.object({
  name: z.string().min(1, 'Enter a name').optional(),
  endpoint: z.string().optional(),
  default_catalog: z.string().optional(),
  options: z.record(z.string(), z.string()).optional(),
});

export type ConnectionPatch = z.infer<typeof connectionPatchSchema>;

/** Body of the credential rotation command. */
export interface CredentialRotate {
  credential_ref?: string;
  token?: string;
}

/** Statuses an import run can hold. */
export const importStatuses = ['pending', 'succeeded', 'failed', 'abandoned'] as const;

export type ImportStatus = (typeof importStatuses)[number];

/** One import run of the read model. */
export const importRunSchema = z.object({
  run_id: z.string(),
  connection_id: z.string(),
  target_catalog_id: z.string(),
  source_catalog: z.string().nullable(),
  include_schemas: z.array(z.string()),
  include_tables: z.record(z.string(), z.array(z.string())),
  schema_mapping: z.record(z.string(), z.string()),
  status: z.string(),
  schema_count: z.number(),
  table_count: z.number(),
  field_count: z.number(),
  error: z.string().nullable(),
  created_at: z.string(),
});

export type ImportRun = z.infer<typeof importRunSchema>;

/** Body shared by the import command and the import plan. */
export interface ImportRequest {
  target_catalog_id: string;
  source_catalog?: string | null;
  include_schemas?: string[];
  include_tables?: Record<string, string[]>;
  schema_mapping?: Record<string, string>;
}

/** One node of an inspected source level. */
export const sourceNodeSchema = z.object({
  name: z.string(),
  raw_type: z.string().optional(),
  mapped_type: z.string().nullable().optional(),
  nullable: z.boolean().optional(),
});

export type SourceNode = z.infer<typeof sourceNodeSchema>;

/** Levels an inspection can answer. */
export type SourceLevel = 'catalogs' | 'schemas' | 'tables' | 'columns';

/** One inspected level of an external source tree. */
export const sourceInspectSchema = z.object({
  node: z.enum(['catalogs', 'schemas', 'tables', 'columns']),
  items: z.array(sourceNodeSchema),
});

export type SourceInspect = z.infer<typeof sourceInspectSchema>;

/** Result of `POST /ingestion/connections/{connection_id}/plan`. */
export const importPlanSchema = z.object({
  schema_count: z.number(),
  table_count: z.number(),
  field_count: z.number(),
  new_schemas: z.array(z.string()),
  new_tables: z.array(z.string()),
  fields_to_change: z.array(z.record(z.string(), z.unknown())),
  unsupported_types: z.array(z.record(z.string(), z.string())),
  warnings: z.array(z.string()),
});

export type ImportPlan = z.infer<typeof importPlanSchema>;

/** Result of `POST /ingestion/connections/{connection_id}/test`. */
export const connectionTestSchema = z.object({
  ok: z.boolean(),
  latency_ms: z.number(),
  error: z.string().nullable(),
});

export type ConnectionTest = z.infer<typeof connectionTestSchema>;

const connectionCreatedSchema = z.object({ connection_id: z.string() });
const runStartedSchema = z.object({ run_id: z.string() });

/**
 * Lists every live connection.
 *
 * @returns The connection rows.
 */
export async function fetchConnections(): Promise<Connection[]> {
  const response = await client.get('/ingestion/connections');
  return connectionSchema.array().parse(response.data);
}

/**
 * Reads one connection.
 *
 * @param connectionId Id of the connection.
 * @returns The connection row.
 */
export async function fetchConnection(connectionId: string): Promise<Connection> {
  const response = await client.get(`/ingestion/connections/${connectionId}`);
  return connectionSchema.parse(response.data);
}

/**
 * Creates a connection.
 *
 * @param body Connection metadata and exactly one credential source.
 * @returns Id of the new connection.
 */
export async function createConnection(body: ConnectionCreate): Promise<string> {
  const response = await client.post('/ingestion/connections', body);
  return connectionCreatedSchema.parse(response.data).connection_id;
}

/**
 * Changes connection metadata without touching the credential.
 *
 * @param connectionId Id of the connection.
 * @param body Fields to change.
 */
export async function changeConnection(connectionId: string, body: ConnectionPatch): Promise<void> {
  await client.patch(`/ingestion/connections/${connectionId}`, body);
}

/**
 * Replaces the credential of a connection.
 *
 * @param connectionId Id of the connection.
 * @param body New inline token or external reference.
 */
export async function rotateCredential(
  connectionId: string,
  body: CredentialRotate,
): Promise<void> {
  await client.post(`/ingestion/connections/${connectionId}/rotate`, body);
}

/**
 * Discards a connection.
 *
 * @param connectionId Id of the connection.
 */
export async function discardConnection(connectionId: string): Promise<void> {
  await client.delete(`/ingestion/connections/${connectionId}`);
}

/**
 * Lists the source kinds the server can build.
 *
 * @returns The kind names.
 */
export async function fetchSourceKinds(): Promise<string[]> {
  const response = await client.get('/ingestion/source-kinds');
  return z
    .object({ kind: z.string() })
    .array()
    .parse(response.data)
    .map((row) => row.kind);
}

/** One local credential profile a source can authenticate with. */
export const sourceProfileSchema = z.object({
  name: z.string(),
  host: z.string().nullable(),
});

export type SourceProfile = z.infer<typeof sourceProfileSchema>;

/**
 * Lists the local credential profiles a source kind can authenticate with.
 *
 * @param kind Source kind whose local profiles are read.
 * @returns The profile names and hosts, never secrets.
 */
export async function fetchSourceProfiles(kind = 'databricks'): Promise<SourceProfile[]> {
  const response = await client.get('/ingestion/source-profiles', { params: { kind } });
  return sourceProfileSchema.array().parse(response.data);
}

/**
 * Probes a connection.
 *
 * @param connectionId Id of the connection.
 * @returns Whether the source answered, with its latency.
 */
export async function testConnection(connectionId: string): Promise<ConnectionTest> {
  const response = await client.post(`/ingestion/connections/${connectionId}/test`);
  return connectionTestSchema.parse(response.data);
}

/** Address of one inspection level. */
export interface InspectParams {
  catalog?: string;
  schema?: string;
  table?: string;
  limit?: number;
}

/**
 * Inspects one level of an external source tree.
 *
 * @param connectionId Id of the connection.
 * @param params Deepest node to inspect.
 * @returns The inspected level and its nodes.
 */
export async function inspectSource(
  connectionId: string,
  params: InspectParams = {},
): Promise<SourceInspect> {
  const response = await client.get(`/ingestion/connections/${connectionId}/inspect`, {
    params,
  });
  return sourceInspectSchema.parse(response.data);
}

/**
 * Previews an import without writing to the target catalog.
 *
 * @param connectionId Id of the connection.
 * @param body Same body as the import command.
 * @returns The planned diff.
 */
export async function planImport(connectionId: string, body: ImportRequest): Promise<ImportPlan> {
  const response = await client.post(`/ingestion/connections/${connectionId}/plan`, body);
  return importPlanSchema.parse(response.data);
}

/**
 * Runs an import and returns the finished run id.
 *
 * The command is synchronous on the server, so the request has no timeout.
 *
 * @param connectionId Id of the connection.
 * @param body Target catalog and the optional source filters.
 * @returns Id of the import run.
 */
export async function startImport(connectionId: string, body: ImportRequest): Promise<string> {
  const response = await client.post(`/ingestion/connections/${connectionId}/import`, body, {
    timeout: LONG_RUNNING_TIMEOUT_MS,
  });
  return runStartedSchema.parse(response.data).run_id;
}

/**
 * Lists import runs, newest last.
 *
 * @param connectionId Optional connection restriction.
 * @returns The run rows.
 */
export async function fetchImportRuns(connectionId?: string): Promise<ImportRun[]> {
  const response = await client.get('/ingestion/runs', {
    params: connectionId === undefined ? {} : { connection_id: connectionId },
  });
  return importRunSchema.array().parse(response.data);
}

/**
 * Reads one import run.
 *
 * @param runId Id of the run.
 * @returns The run row.
 */
export async function fetchImportRun(runId: string): Promise<ImportRun> {
  const response = await client.get(`/ingestion/runs/${runId}`);
  return importRunSchema.parse(response.data);
}
