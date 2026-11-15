import { catalogPath, columnPath, schemaPath, tablePath } from './catalog-routes';
import { domainPath, termPath } from './vocabulary-routes';
import { workspacePath } from './semantic-routes';

/**
 * Matches one object URN inside running text.
 *
 * The values are not validated here: `parseUrn` decides whether the URN names a
 * real page, so a malformed one keeps rendering as plain text.
 */
export const URN_PATTERN = /\burn:(?:catalog|vocabulary|semantic)(?:\/[^\s/]+)+/g;

/**
 * Punctuation a sentence may glue onto a URN.
 *
 * The answer is written in the language of the reader, so the full-width forms
 * count as punctuation too: a URN inside Chinese brackets ends with `）`, not
 * with `)`.
 */
const TRAILING = /[.,;:!?)\]）】」』，。；：！？、]+$/;

const SCHEMA_KEYWORDS = new Set(['schema', 'schemas']);
const TABLE_KEYWORDS = new Set(['table', 'tables']);
const COLUMN_KEYWORDS = new Set(['column', 'columns', 'field', 'fields']);
const TERM_KEYWORDS = new Set(['term', 'terms']);
const ENTITY_KEYWORDS = new Set(['entity', 'entities']);
const RELATIONSHIP_KEYWORDS = new Set(['relationship', 'relationships']);

/** Object a lookup can describe by id. */
export interface UrnReference {
  /** Kind of the object, as the target lookup names it. */
  type:
    | 'catalog'
    | 'schema'
    | 'table'
    | 'semantic_model'
    | 'semantic_entity'
    | 'relationship'
    | 'domain'
    | 'term';
  /** Id of the object. */
  id: string;
}

/** One resolved object URN. */
export interface UrnTarget {
  /** The URN as the model wrote it, without trailing punctuation. */
  urn: string;
  /** In-app path the chat links to. */
  href: string;
  /** Text rendered instead of the URN until a name is known. */
  label: string;
  /**
   * Object a lookup can describe, or `null` when the last segment already is
   * its name (a column, an entity) and nothing needs resolving.
   */
  reference: UrnReference | null;
}

/**
 * Shortens an id for the link text.
 *
 * @param value Id or name.
 * @returns The first eight characters of a UUID, the value itself otherwise.
 */
function shorten(value: string): string {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(value) ? `${value.slice(0, 8)}…` : value;
}

/**
/**
 * Resolves a `urn:catalog/...` chain.
 *
 * @param urn Full URN.
 * @param catalogId Catalog id.
 * @param rest Keyword and value segments after the catalog id.
 * @returns The link target, or `null` when the chain is malformed.
 */
function catalogTarget(urn: string, catalogId: string, rest: string[]): UrnTarget | null {
  if (rest.length % 2 !== 0) {
    return null;
  }
  const ids: { schema?: string; table?: string; column?: string } = {};
  for (let index = 0; index + 1 < rest.length; index += 2) {
    const keyword = (rest[index] ?? '').toLowerCase();
    const value = rest[index + 1] ?? '';
    if (value === '') {
      return null;
    }
    if (SCHEMA_KEYWORDS.has(keyword)) {
      if (ids.schema !== undefined) {
        return null;
      }
      ids.schema = value;
    } else if (TABLE_KEYWORDS.has(keyword)) {
      if (ids.schema === undefined || ids.table !== undefined) {
        return null;
      }
      ids.table = value;
    } else if (COLUMN_KEYWORDS.has(keyword)) {
      if (ids.table === undefined || ids.column !== undefined) {
        return null;
      }
      ids.column = value;
    } else {
      return null;
    }
  }
  if (ids.schema !== undefined && ids.table !== undefined && ids.column !== undefined) {
    return {
      urn,
      href: columnPath(catalogId, ids.schema, ids.table, ids.column),
      label: shorten(ids.column),
      // A column is named, not addressed by id, so there is nothing to look up.
      reference: null,
    };
  }
  if (ids.schema !== undefined && ids.table !== undefined) {
    return {
      urn,
      href: tablePath(catalogId, ids.schema, ids.table),
      label: shorten(ids.table),
      reference: { type: 'table', id: ids.table },
    };
  }
  if (ids.schema !== undefined) {
    return {
      urn,
      href: schemaPath(catalogId, ids.schema),
      label: shorten(ids.schema),
      reference: { type: 'schema', id: ids.schema },
    };
  }
  return {
    urn,
    href: catalogPath(catalogId),
    label: shorten(catalogId),
    reference: { type: 'catalog', id: catalogId },
  };
}

/**
 * Resolves a `urn:vocabulary/...` chain.
 *
 * @param urn Full URN.
 * @param domainId Domain id.
 * @param rest Keyword and value segments after the domain id.
 * @returns The link target, or `null` when the chain is malformed.
 */
function vocabularyTarget(urn: string, domainId: string, rest: string[]): UrnTarget | null {
  if (rest.length === 0) {
    return {
      urn,
      href: domainPath(domainId),
      label: shorten(domainId),
      reference: { type: 'domain', id: domainId },
    };
  }
  const keyword = (rest[0] ?? '').toLowerCase();
  const termId = rest[1];
  if (rest.length !== 2 || termId === undefined || !TERM_KEYWORDS.has(keyword)) {
    return null;
  }
  return {
    urn,
    href: termPath(domainId, termId),
    label: shorten(termId),
    reference: { type: 'term', id: termId },
  };
}

/**
 * Resolves a `urn:semantic/...` chain.
 *
 * @param urn Full URN.
 * @param modelId Model id.
 * @param rest Keyword and value segments after the model id.
 * @returns The link target, or `null` when the chain is malformed.
 */
function semanticTarget(urn: string, modelId: string, rest: string[]): UrnTarget | null {
  if (rest.length === 0) {
    return {
      urn,
      href: workspacePath(modelId),
      label: shorten(modelId),
      reference: { type: 'semantic_model', id: modelId },
    };
  }
  const keyword = (rest[0] ?? '').toLowerCase();
  const value = rest[1];
  if (rest.length !== 2 || value === undefined) {
    return null;
  }
  if (ENTITY_KEYWORDS.has(keyword)) {
    return {
      urn,
      href: workspacePath(modelId, { entity: value }),
      // An entity is named, not addressed by id, so nothing needs resolving.
      label: shorten(value),
      reference: null,
    };
  }
  if (RELATIONSHIP_KEYWORDS.has(keyword)) {
    return {
      urn,
      href: workspacePath(modelId, { relationship: value }),
      label: shorten(value),
      reference: { type: 'relationship', id: value },
    };
  }
  return null;
}

/**
 * Parses an object URN into the page it points at.
 *
 * Grammar: `urn:catalog/<catalog>[/schema/<schema>[/table/<table>
 * [/field/<column>]]]`, `urn:vocabulary/<domain>[/term/<term>]` and
 * `urn:semantic/<model>[/entity/<entity>|/relationship/<id>]`. `field` and
 * `column` are synonyms, because the catalog UI calls a column what the MCP
 * surface calls a field. A URN with a keyword out of order, a missing value or an
 * unknown keyword answers `null`, so the caller leaves the text alone.
 *
 * @param raw URN as the model wrote it.
 * @returns The link target, or `null` when the URN does not name a page.
 */
export function parseUrn(raw: string): UrnTarget | null {
  const urn = raw.replace(TRAILING, '');
  const segments = urn.split('/').filter((segment) => segment !== '');
  const head = segments[0];
  const id = segments[1];
  if (head === undefined || id === undefined) {
    return null;
  }
  if (head === 'urn:catalog') {
    return catalogTarget(urn, id, segments.slice(2));
  }
  if (head === 'urn:vocabulary') {
    return vocabularyTarget(urn, id, segments.slice(2));
  }
  if (head === 'urn:semantic') {
    return semanticTarget(urn, id, segments.slice(2));
  }
  return null;
}

/**
 * Collects the object URNs of one text.
 *
 * The URNs are deduplicated, so a text that names the same object twice costs
 * one lookup.
 *
 * @param text Text or markdown to scan.
 * @returns Every resolved URN, in order of appearance.
 */
export function urnsIn(text: string): UrnTarget[] {
  URN_PATTERN.lastIndex = 0;
  const found: UrnTarget[] = [];
  const seen = new Set<string>();
  for (let match = URN_PATTERN.exec(text); match !== null; match = URN_PATTERN.exec(text)) {
    const target = parseUrn(match[0]);
    if (target === null || seen.has(target.urn)) {
      continue;
    }
    seen.add(target.urn);
    found.push(target);
  }
  return found;
}
