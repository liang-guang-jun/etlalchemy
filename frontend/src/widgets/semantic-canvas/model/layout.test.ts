import { describe, expect, it } from 'vitest';

import {
  alignToCenter,
  centerOf,
  FALLBACK_CARD_SIZE,
  layoutDiagram,
  overlappingPairs,
  type CardRect,
  type LayoutNode,
} from './layout';

/**
 * Builds a card of a fixed size.
 *
 * @param id Entity name.
 * @param height Card height.
 * @returns The layout node.
 */
function card(id: string, height = 72): LayoutNode {
  return { id, size: { width: 208, height } };
}

/**
 * Reads one position, failing the test when it is missing.
 *
 * @param positions Layout result.
 * @param id Entity name.
 * @returns The position of that card.
 */
function at(
  positions: Map<string, { x: number; y: number }>,
  id: string,
): { x: number; y: number } {
  const position = positions.get(id);
  if (position === undefined) {
    throw new Error(`no position for ${id}`);
  }
  return position;
}

describe('layoutDiagram', () => {
  it('places a single card at the origin', () => {
    const positions = layoutDiagram([card('Account')], []);

    expect(at(positions, 'Account')).toEqual({ x: 0, y: 0 });
  });

  it('puts the target of a relationship to the right of its source', () => {
    const positions = layoutDiagram(
      [card('Order'), card('Account')],
      [{ source: 'Order', target: 'Account' }],
    );

    expect(at(positions, 'Account').x).toBeGreaterThan(at(positions, 'Order').x);
  });

  it('stacks cards of the same column without overlapping them', () => {
    const positions = layoutDiagram(
      [card('Account', 400), card('Rep', 500), card('Region', 300)],
      [],
      { nodeGap: 48 },
    );

    const cards: CardRect[] = [
      { id: 'Account', ...at(positions, 'Account'), width: 208, height: 400 },
      { id: 'Rep', ...at(positions, 'Rep'), width: 208, height: 500 },
      { id: 'Region', ...at(positions, 'Region'), width: 208, height: 300 },
    ];
    expect(overlappingPairs(cards)).toEqual([]);
  });

  it('leaves at least the requested gap between two cards of a column', () => {
    const positions = layoutDiagram([card('Account', 300), card('Rep', 200)], [], {
      nodeGap: 48,
    });

    const account = at(positions, 'Account');
    const rep = at(positions, 'Rep');
    const gap = Math.max(rep.y - (account.y + 300), account.y - (rep.y + 200));
    expect(gap).toBeGreaterThanOrEqual(48);
  });

  it('orders a chain left to right', () => {
    const positions = layoutDiagram(
      [card('A'), card('B'), card('C')],
      [
        { source: 'A', target: 'B' },
        { source: 'B', target: 'C' },
      ],
    );

    expect(at(positions, 'A').x).toBeLessThan(at(positions, 'B').x);
    expect(at(positions, 'B').x).toBeLessThan(at(positions, 'C').x);
  });

  it('ignores edges to cards that are not placed and parallel references', () => {
    const positions = layoutDiagram(
      [card('Order'), card('Account')],
      [
        { source: 'Order', target: 'Account' },
        { source: 'Order', target: 'Account' },
        { source: 'Order', target: 'Missing' },
      ],
    );

    expect(positions.size).toBe(2);
    expect(at(positions, 'Account').x).toBeGreaterThan(at(positions, 'Order').x);
  });

  it('is deterministic for the same input', () => {
    const nodes = [card('A', 120), card('B', 80), card('C', 200), card('D', 90)];
    const edges = [
      { source: 'A', target: 'B' },
      { source: 'A', target: 'C' },
      { source: 'D', target: 'C' },
    ];

    expect([...layoutDiagram(nodes, edges)]).toEqual([...layoutDiagram(nodes, edges)]);
  });

  it('returns nothing for an empty diagram', () => {
    expect(layoutDiagram([], []).size).toBe(0);
  });
});

describe('overlappingPairs', () => {
  it('treats touching cards as adjacent', () => {
    const cards: CardRect[] = [
      { id: 'a', x: 0, y: 0, width: 200, height: 100 },
      { id: 'b', x: 0, y: 108, width: 200, height: 100 },
    ];

    expect(overlappingPairs(cards)).toEqual([]);
  });

  it('reports the cards that cover each other', () => {
    const cards: CardRect[] = [
      { id: 'a', x: 0, y: 0, width: 200, height: 100 },
      { id: 'b', x: 0, y: 60, width: 200, height: 100 },
      { id: 'c', x: 400, y: 0, width: 200, height: 100 },
    ];

    expect(overlappingPairs(cards)).toEqual([['a', 'b']]);
  });
});

describe('centerOf', () => {
  it('returns the middle of the bounding box', () => {
    expect(
      centerOf([
        { id: 'a', x: 0, y: 0, width: 100, height: 100 },
        { id: 'b', x: 200, y: 100, width: 100, height: 100 },
      ]),
    ).toEqual({ x: 150, y: 100 });
  });

  it('returns null for an empty diagram', () => {
    expect(centerOf([])).toBeNull();
  });
});

describe('alignToCenter', () => {
  it('moves the layout so its centre lands on the target', () => {
    const sizes = new Map([['a', FALLBACK_CARD_SIZE]]);
    const shifted = alignToCenter(new Map([['a', { x: 0, y: 0 }]]), sizes, { x: 500, y: 300 });

    const position = shifted.get('a');
    expect(position).toEqual({
      x: 500 - FALLBACK_CARD_SIZE.width / 2,
      y: 300 - FALLBACK_CARD_SIZE.height / 2,
    });
  });
});
