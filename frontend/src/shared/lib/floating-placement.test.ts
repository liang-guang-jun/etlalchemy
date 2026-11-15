import { describe, expect, it } from 'vitest';

import { clampToViewport, placePanel } from './floating-placement';

const VIEWPORT = { x: 0, y: 0, width: 1440, height: 900 };
const PANEL = { x: 0, y: 0, width: 400, height: 600 };

/** Builds the rectangle of a 56px icon at the given top-left corner. */
function icon(x: number, y: number) {
  return { x, y, width: 56, height: 56 };
}

describe('placePanel', () => {
  it('opens upwards and to the left of a bottom-right icon', () => {
    const placement = placePanel(icon(1360, 820), PANEL, VIEWPORT);

    expect(placement.side).toBe('top');
    expect(placement.top + PANEL.height).toBeLessThanOrEqual(820);
    expect(placement.left + PANEL.width).toBeLessThanOrEqual(VIEWPORT.width - 12);
  });

  it('opens to the right of an icon dragged to the left edge', () => {
    const placement = placePanel(icon(8, 420), PANEL, VIEWPORT);

    expect(placement.side).toBe('right');
    expect(placement.left).toBe(8 + 56 + 12);
    // Centred on the icon instead of pinned to an edge.
    expect(placement.top).toBe(420 + 28 - 300);
  });

  it('opens downwards from an icon dragged to the top edge', () => {
    const placement = placePanel(icon(700, 4), PANEL, VIEWPORT);

    expect(placement.side).toBe('bottom');
    expect(placement.top).toBe(4 + 56 + 12);
  });

  it('clamps a panel that cannot fit next to the anchor', () => {
    const small = { x: 0, y: 0, width: 420, height: 620 };
    const placement = placePanel(icon(380, 300), PANEL, small);

    expect(placement.left).toBeGreaterThanOrEqual(12);
    expect(placement.top).toBeGreaterThanOrEqual(12);
    expect(placement.left).toBeLessThanOrEqual(small.width);
    expect(placement.top).toBeLessThanOrEqual(small.height);
  });
});

describe('clampToViewport', () => {
  it('keeps a dragged icon inside the viewport', () => {
    expect(clampToViewport({ x: -40, y: 2000 }, 56, { width: 1440, height: 900 })).toEqual({
      x: 0,
      y: 844,
    });
  });

  it('leaves an icon that already fits untouched', () => {
    expect(clampToViewport({ x: 120, y: 240 }, 56, { width: 1440, height: 900 })).toEqual({
      x: 120,
      y: 240,
    });
  });
});
