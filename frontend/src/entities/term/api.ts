import { z } from 'zod';

import { client } from '@/shared/api/client';

/** A term without its aliases and links. */
export const termSummarySchema = z.object({
  term_id: z.string(),
  domain_id: z.string(),
  parent_id: z.string().nullable(),
  path: z.string(),
  name: z.string(),
  definition: z.string(),
  status: z.string(),
  color: z.string().default(''),
});

export type TermSummary = z.infer<typeof termSummarySchema>;

/** One catalog link of a term. */
export const termLinkSchema = z.object({
  target_id: z.string(),
  target_kind: z.string(),
  field_name: z.string(),
  status: z.string().nullable().optional(),
  target_name: z.string().nullable().optional(),
  catalog_id: z.string().nullable().optional(),
  schema_id: z.string().nullable().optional(),
  table_id: z.string().nullable().optional(),
});

export type TermLink = z.infer<typeof termLinkSchema>;

/** A term with its aliases and catalog links. */
export const termSchema = termSummarySchema.extend({
  aliases: z.array(z.string()),
  links: z.array(termLinkSchema),
});

export type Term = z.infer<typeof termSchema>;

/** One hit of the vocabulary search. */
export const termSearchResultSchema = z.object({
  domain_id: z.string(),
  domain_name: z.string(),
  term_id: z.string(),
  term_path: z.string(),
  term_name: z.string(),
  definition: z.string(),
  status: z.string(),
  matched_alias: z.string().nullable(),
  color: z.string().default(''),
});

export type TermSearchResult = z.infer<typeof termSearchResultSchema>;

const termCreatedSchema = z.object({ term_id: z.string() });

/** Kinds a term can be linked to. */
export const TARGET_KINDS = ['catalog', 'schema', 'table', 'field'] as const;

/**
 * Lists the live terms of a domain.
 *
 * @param domainId Id of the domain.
 * @param status Optional lifecycle status filter.
 * @returns The term summaries ordered by path.
 */
export async function fetchTerms(domainId: string, status?: string): Promise<TermSummary[]> {
  const response = await client.get(`/vocabulary/domains/${domainId}/terms`, {
    params: status === undefined ? {} : { status },
  });
  return termSummarySchema.array().parse(response.data);
}

/**
 * Reads one term with its aliases and links.
 *
 * @param domainId Id of the domain.
 * @param termId Id of the term.
 * @returns The term.
 */
export async function fetchTerm(domainId: string, termId: string): Promise<Term> {
  const response = await client.get(`/vocabulary/domains/${domainId}/terms/${termId}`);
  return termSchema.parse(response.data);
}

/**
 * Creates a term under an optional parent.
 *
 * @param domainId Id of the domain.
 * @param body Term fields; `parent` accepts a path or an id.
 * @returns Id of the new term.
 */
export async function createTerm(
  domainId: string,
  body: {
    name: string;
    definition: string;
    aliases: string[];
    parent: string | null;
    color: string;
  },
): Promise<string> {
  const response = await client.post(`/vocabulary/domains/${domainId}/terms`, body);
  return termCreatedSchema.parse(response.data).term_id;
}

/**
 * Changes a term.
 *
 * @param domainId Id of the domain.
 * @param termId Id of the term.
 * @param body Fields to change.
 */
export async function changeTerm(
  domainId: string,
  termId: string,
  body: {
    name?: string;
    definition?: string;
    aliases_add?: string[];
    aliases_remove?: string[];
    color?: string;
  },
): Promise<void> {
  await client.patch(`/vocabulary/domains/${domainId}/terms/${termId}`, body);
}

/**
 * Moves a term under another parent.
 *
 * @param domainId Id of the domain.
 * @param termId Id of the term.
 * @param newParent Parent path or id, or `null` for the top level.
 */
export async function moveTerm(
  domainId: string,
  termId: string,
  newParent: string | null,
): Promise<void> {
  await client.post(`/vocabulary/domains/${domainId}/terms/${termId}/move`, {
    new_parent: newParent,
  });
}

/**
 * Discards a term and its descendants.
 *
 * @param domainId Id of the domain.
 * @param termId Id of the term.
 */
export async function discardTerm(domainId: string, termId: string): Promise<void> {
  await client.delete(`/vocabulary/domains/${domainId}/terms/${termId}`);
}

/** Lifecycle commands of a term. */
export type TermTransition = 'approve' | 'reopen' | 'deprecate' | 'reactivate';

/**
 * Applies a lifecycle command.
 *
 * @param domainId Id of the domain.
 * @param termId Id of the term.
 * @param transition Command to apply.
 * @param argument Optional reviewer or reason.
 */
export async function transitionTerm(
  domainId: string,
  termId: string,
  transition: TermTransition,
  argument: string,
): Promise<void> {
  const param = transition === 'approve' ? 'reviewer' : 'reason';
  await client.post(`/vocabulary/domains/${domainId}/terms/${termId}/${transition}`, null, {
    params: argument === '' ? {} : { [param]: argument },
  });
}

/**
 * Links a term to a catalog object.
 *
 * @param domainId Id of the domain.
 * @param termId Id of the term.
 * @param body Link target; `target_id` is the owning table for `field` links.
 */
export async function linkTerm(
  domainId: string,
  termId: string,
  body: { target_id: string; target_kind: string; field_name?: string },
): Promise<void> {
  await client.post(`/vocabulary/domains/${domainId}/terms/${termId}/links`, null, {
    params: {
      target_id: body.target_id,
      target_kind: body.target_kind,
      field_name: body.field_name ?? '',
    },
  });
}

/**
 * Removes a catalog link from a term.
 *
 * @param domainId Id of the domain.
 * @param termId Id of the term.
 * @param body Link target.
 */
export async function unlinkTerm(
  domainId: string,
  termId: string,
  body: { target_id: string; target_kind: string; field_name?: string },
): Promise<void> {
  await client.delete(`/vocabulary/domains/${domainId}/terms/${termId}/links`, {
    params: {
      target_id: body.target_id,
      target_kind: body.target_kind,
      field_name: body.field_name ?? '',
    },
  });
}

/**
 * Lists the terms linked to one field of a table.
 *
 * @param tableId Id of the owning table.
 * @param fieldName Name of the field.
 * @returns The linked term summaries.
 */
export async function fetchTermsForField(
  tableId: string,
  fieldName: string,
): Promise<TermSummary[]> {
  const response = await client.get('/vocabulary/terms-for-field', {
    params: { table_id: tableId, field_name: fieldName },
  });
  return termSummarySchema.array().parse(response.data);
}

/**
 * Lists the terms linked to exactly one catalog object.
 *
 * @param targetId Id of the catalog, schema or table, or of the owning table for a field.
 * @param targetKind One of `catalog`, `schema`, `table` or `field`.
 * @param fieldName Field name for `field` targets, empty otherwise.
 * @returns The linked term summaries.
 */
export async function fetchTermsForTarget(
  targetId: string,
  targetKind: string,
  fieldName = '',
): Promise<TermSummary[]> {
  const response = await client.get('/vocabulary/terms-for-target', {
    params: { target_id: targetId, target_kind: targetKind, field_name: fieldName },
  });
  return termSummarySchema.array().parse(response.data);
}

/**
 * Lists the terms linked to a table or to any of its fields.
 *
 * @param tableId Id of the table.
 * @returns The linked term summaries.
 */
export async function fetchTermsForTable(tableId: string): Promise<TermSummary[]> {
  const response = await client.get('/vocabulary/terms-for-table', {
    params: { table_id: tableId },
  });
  return termSummarySchema.array().parse(response.data);
}

/**
 * Searches terms by name, definition or alias.
 *
 * @param q Search text.
 * @param domainId Optional domain restriction.
 * @returns The matching terms.
 */
export async function searchTerms(q: string, domainId?: string): Promise<TermSearchResult[]> {
  const response = await client.get('/vocabulary/search', {
    params: domainId === undefined ? { q } : { q, domain_id: domainId },
  });
  return termSearchResultSchema.array().parse(response.data);
}
