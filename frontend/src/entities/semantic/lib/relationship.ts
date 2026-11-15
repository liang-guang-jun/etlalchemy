import type { Relationship } from '../api';

/**
 * Priority that marks a relationship as inactive.
 *
 * An inactive relationship is still stored, but the canvas draws it as a grey
 * dashed line and it takes no part in filter propagation.
 */
export const INACTIVE_PRIORITY = -1;

/**
 * Tells whether a relationship is switched off.
 *
 * @param relationship Relationship or any object carrying its priority.
 * @returns `true` when the priority is {@link INACTIVE_PRIORITY}.
 */
export function isInactive(relationship: Pick<Relationship, 'priority'>): boolean {
  return relationship.priority === INACTIVE_PRIORITY;
}

/**
 * Reports whether swapping the two sides leaves a cardinality the backend
 * cannot express.
 *
 * The enum only has `one_to_many`, `one_to_one` and `many_to_many` — there is no
 * `many_to_one` — so a swapped `one_to_many` keeps its value and the editor has
 * to ask the user to review it.
 *
 * @param cardinality Cardinality before the swap.
 * @returns `true` when the mirrored cardinality is not available.
 */
export function cardinalityNeedsReviewAfterSwap(cardinality: string): boolean {
  return cardinality === 'one_to_many';
}

/**
 * Keeps the priority inside the range the editor offers.
 *
 * `-1` is the inactive marker and nothing below it is meaningful, so a smaller
 * value is corrected instead of being sent to the backend.
 *
 * @param value Raw input value.
 * @returns The clamped integer, or `0` for an empty input.
 */
export function clampPriority(value: string): number {
  const parsed = Number.parseInt(value, 10);
  if (Number.isNaN(parsed)) {
    return 0;
  }
  return Math.max(INACTIVE_PRIORITY, parsed);
}
