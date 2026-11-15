import { describe, expect, it } from 'vitest';

import {
  cardinalityNeedsReviewAfterSwap,
  clampPriority,
  INACTIVE_PRIORITY,
  isInactive,
} from './relationship';

describe('isInactive', () => {
  it('treats only -1 as inactive', () => {
    expect(isInactive({ priority: INACTIVE_PRIORITY })).toBe(true);
    expect(isInactive({ priority: 0 })).toBe(false);
    expect(isInactive({ priority: 40 })).toBe(false);
  });
});

describe('cardinalityNeedsReviewAfterSwap', () => {
  it('asks for a review when the mirror would be many-to-one', () => {
    expect(cardinalityNeedsReviewAfterSwap('one_to_many')).toBe(true);
  });

  it('keeps the symmetric cardinalities as they are', () => {
    expect(cardinalityNeedsReviewAfterSwap('one_to_one')).toBe(false);
    expect(cardinalityNeedsReviewAfterSwap('many_to_many')).toBe(false);
  });
});

describe('clampPriority', () => {
  it('keeps the inactive marker', () => {
    expect(clampPriority('-1')).toBe(-1);
  });

  it('clamps anything below the marker', () => {
    expect(clampPriority('-7')).toBe(-1);
  });

  it('keeps positive values', () => {
    expect(clampPriority('12')).toBe(12);
  });

  it('falls back to active for an empty input', () => {
    expect(clampPriority('')).toBe(0);
  });
});
