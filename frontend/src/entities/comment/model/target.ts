import { columnPath, catalogPath, schemaPath, tablePath } from '@/shared/lib/catalog-routes';
import { workspacePath } from '@/shared/lib/semantic-routes';
import { domainPath, termPath } from '@/shared/lib/vocabulary-routes';

/** Types the comment context resolves as a target. */
export type CommentTargetType =
  | 'catalog'
  | 'schema'
  | 'table'
  | 'field'
  | 'semantic_model'
  | 'semantic_entity'
  | 'relationship'
  | 'term'
  | 'domain'
  | 'ingestion_connection'
  | 'import_run';

/** One object a discussion can hang off. */
export interface CommentTarget {
  /** Type of the commented element. */
  type: CommentTargetType;
  /** Id of the commented element. */
  id: string;
  /** Name the panel header shows. */
  label: string;
  /** Deep link to the object's page, when the caller knows it. */
  href?: string;
}

/** What the backend knows about a target: its name and the ids that lead to it. */
export interface TargetDescription {
  target_type: CommentTargetType;
  target_id: string;
  name: string;
  path: string;
  catalog_id: string | null;
  schema_name: string | null;
  table_name: string | null;
  field_name: string | null;
  model_id: string | null;
  entity_name: string | null;
  domain_id: string | null;
}

/** Noun shown next to the target name, per target type. */
export const TARGET_NOUNS: Record<CommentTargetType, string> = {
  catalog: 'Catalog',
  schema: 'Schema',
  table: 'Table',
  field: 'Field',
  semantic_model: 'Model',
  semantic_entity: 'Entity',
  relationship: 'Relationship',
  term: 'Term',
  domain: 'Domain',
  ingestion_connection: 'Connection',
  import_run: 'Import run',
};

/**
 * Builds the panel title of a target.
 *
 * @param target Target to describe.
 * @returns A label such as `Table: ad_spend`.
 */
export function targetTitle(target: CommentTarget): string {
  return `${TARGET_NOUNS[target.type]}: ${target.label}`;
}

/**
 * Builds the deep link of a described target.
 *
 * The backend knows the ids of every level the target sits in, so the frontend
 * turns them into a route with the same helpers its own pages use.
 *
 * @param description Target described by `GET /comments/targets`.
 * @returns The route of the object, or `undefined` when a needed id is missing.
 */
export function targetHref(description: TargetDescription): string | undefined {
  const { catalog_id: catalogId, schema_name: schema, domain_id: domainId } = description;
  switch (description.target_type) {
    case 'catalog':
      return catalogId === null ? undefined : catalogPath(catalogId);
    case 'schema':
      return catalogId === null || schema === null ? undefined : schemaPath(catalogId, schema);
    case 'table':
      return catalogId === null || schema === null || description.table_name === null
        ? undefined
        : tablePath(catalogId, schema, description.table_name);
    case 'field':
      return catalogId === null ||
        schema === null ||
        description.table_name === null ||
        description.field_name === null
        ? undefined
        : columnPath(catalogId, schema, description.table_name, description.field_name);
    case 'semantic_model':
      return description.model_id === null ? undefined : workspacePath(description.model_id);
    case 'semantic_entity':
      return description.model_id === null || description.entity_name === null
        ? undefined
        : workspacePath(description.model_id, { entity: description.entity_name });
    case 'relationship':
      return description.model_id === null
        ? undefined
        : workspacePath(description.model_id, { relationship: description.target_id });
    case 'domain':
      return domainId === null ? undefined : domainPath(domainId);
    case 'term':
      return domainId === null ? undefined : termPath(domainId, description.target_id);
    default:
      return undefined;
  }
}

/**
 * Turns a described target into the value the panel opens with.
 *
 * @param description Target described by `GET /comments/targets`.
 * @returns The target to hand to `openComments`.
 */
export function describedTarget(description: TargetDescription): CommentTarget {
  const href = targetHref(description);
  return {
    type: description.target_type,
    id: description.target_id,
    label: description.name,
    ...(href === undefined ? {} : { href }),
  };
}
