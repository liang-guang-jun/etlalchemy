import type { FieldRef, Relationship } from '../api';

/**
 * Formats one `entity.field` reference.
 *
 * @param ref Reference to format.
 * @returns The dotted label.
 */
export function refLabel(ref: FieldRef): string {
  return `${ref.entity}.${ref.field}`;
}

/**
 * Builds the short `from → to` summary of a relationship.
 *
 * Extra field pairs are folded into a `(+n)` marker so a multi-column relation
 * stays on one line.
 *
 * @param relationship Relationship to summarise.
 * @returns The summary text.
 */
export function relationshipSummary(relationship: Relationship): string {
  const from = relationship.from_refs[0];
  const to = relationship.to_refs[0];
  if (from === undefined || to === undefined) {
    return 'empty relationship';
  }
  const head = `${from.entity} → ${to.entity}`;
  const extra = relationship.from_refs.length - 1;
  return extra > 0 ? `${head} (+${extra})` : head;
}

/**
 * Builds the field-level detail of a relationship.
 *
 * @param relationship Relationship to describe.
 * @returns The paired field references, separated by commas.
 */
export function relationshipDetail(relationship: Relationship): string {
  return relationship.from_refs
    .map((from, index) => {
      const to = relationship.to_refs[index];
      return to === undefined ? refLabel(from) : `${refLabel(from)} → ${refLabel(to)}`;
    })
    .join(', ');
}

/**
 * Shortens a cardinality value for the canvas.
 *
 * @param cardinality Cardinality as stored by the backend.
 * @returns `1:1`, `1:N` or `N:N`.
 */
export function cardinalityLabel(cardinality: string): string {
  switch (cardinality) {
    case 'one_to_one':
      return '1:1';
    case 'one_to_many':
      return '1:N';
    case 'many_to_many':
      return 'N:N';
    default:
      return cardinality;
  }
}
