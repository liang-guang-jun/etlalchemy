import dagre from '@dagrejs/dagre';

/** Size of one card on the canvas, in flow units. */
export interface CardSize {
  /** Card width. */
  width: number;
  /** Card height. */
  height: number;
}

/** One card handed to the layout engine. */
export interface LayoutNode {
  /** Entity name of the card. */
  id: string;
  /** Measured size of the card; cards that were never rendered fall back to {@link FALLBACK_CARD_SIZE}. */
  size: CardSize;
}

/** One relationship between two placed cards. */
export interface LayoutEdge {
  /** Entity the relationship starts at. */
  source: string;
  /** Entity the relationship points at. */
  target: string;
}

/** Position of an entity in flow coordinates. */
export interface LayoutPosition {
  /** Horizontal offset of the card's top-left corner. */
  x: number;
  /** Vertical offset of the card's top-left corner. */
  y: number;
}

/** Rectangle occupied by one card. */
export interface CardRect extends CardSize {
  /** Entity name of the card. */
  id: string;
  /** Horizontal offset of the card's top-left corner. */
  x: number;
  /** Vertical offset of the card's top-left corner. */
  y: number;
}

/** Spacing knobs of the layout. */
export interface LayoutOptions {
  /** Vertical gap between two cards of the same column. */
  nodeGap?: number;
  /** Horizontal gap between two columns. */
  rankGap?: number;
}

/** Size used for a card that React Flow has not measured yet. */
export const FALLBACK_CARD_SIZE: CardSize = { width: 208, height: 72 };

/**
 * Cards are laid out column by column, following the relationships: a table
 * that another one references sits to the right of it, so most edges run
 * left to right. The vertical gap uses the measured card heights, so a card
 * expanded to all of its columns never collides with the card below it.
 */
const DEFAULT_NODE_GAP = 48;

/** Horizontal gap between two columns, wide enough for the cardinality label. */
const DEFAULT_RANK_GAP = 140;

/**
 * Tolerance below which two cards are considered adjacent, not overlapping.
 */
const OVERLAP_TOLERANCE = 8;

/**
 * Places the cards with dagre, rank by rank, and returns their new corners.
 *
 * The result is normalised: the top-left card sits at `(0, 0)`, so callers can
 * translate the whole diagram without knowing where dagre put it.
 *
 * @param nodes Cards to place.
 * @param edges Relationships between the cards; edges to unplaced cards are ignored.
 * @param options Spacing overrides.
 * @returns The new top-left corner of each card, keyed by entity name.
 */
export function layoutDiagram(
  nodes: readonly LayoutNode[],
  edges: readonly LayoutEdge[],
  options: LayoutOptions = {},
): Map<string, LayoutPosition> {
  const graph = new dagre.graphlib.Graph({ multigraph: true });
  graph.setGraph({
    rankdir: 'LR',
    nodesep: options.nodeGap ?? DEFAULT_NODE_GAP,
    ranksep: options.rankGap ?? DEFAULT_RANK_GAP,
    marginx: 0,
    marginy: 0,
    ranker: 'network-simplex',
  });
  graph.setDefaultEdgeLabel(() => ({}));

  for (const node of nodes) {
    graph.setNode(node.id, { width: node.size.width, height: node.size.height });
  }

  const placed = new Set(nodes.map((node) => node.id));
  const seen = new Set<string>();
  for (const edge of edges) {
    if (edge.source === edge.target || !placed.has(edge.source) || !placed.has(edge.target)) {
      continue;
    }
    // Parallel field references pair the same two cards; one edge is enough to
    // influence the rank order and keeping it unique keeps the layout stable.
    const key = `${edge.source}->${edge.target}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    graph.setEdge(edge.source, edge.target, {}, key);
  }

  dagre.layout(graph);

  const positions = new Map<string, LayoutPosition>();
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  for (const node of nodes) {
    const laid = graph.node(node.id) as { x?: number; y?: number } | undefined;
    if (laid?.x === undefined || laid.y === undefined) {
      positions.set(node.id, { x: 0, y: 0 });
      continue;
    }
    // Dagre reports the centre of a node.
    const x = Math.round(laid.x - node.size.width / 2);
    const y = Math.round(laid.y - node.size.height / 2);
    positions.set(node.id, { x, y });
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
  }

  if (positions.size === 0 || !Number.isFinite(minX) || !Number.isFinite(minY)) {
    return positions;
  }
  for (const [id, position] of positions) {
    positions.set(id, { x: position.x - minX, y: position.y - minY });
  }
  return positions;
}

/**
 * Reports the cards that cover each other.
 *
 * A tiny tolerance keeps cards that merely touch from counting as overlapping,
 * so a tidy grid is never re-laid-out just because two cards share an edge.
 *
 * @param cards Rectangles of all placed cards.
 * @returns The ids of every overlapping pair.
 */
export function overlappingPairs(cards: readonly CardRect[]): [string, string][] {
  const pairs: [string, string][] = [];
  for (let index = 0; index < cards.length; index += 1) {
    const left = cards[index];
    if (left === undefined) {
      continue;
    }
    for (let other = index + 1; other < cards.length; other += 1) {
      const right = cards[other];
      if (right === undefined) {
        continue;
      }
      const overlapsX =
        left.x + left.width - OVERLAP_TOLERANCE > right.x &&
        right.x + right.width - OVERLAP_TOLERANCE > left.x;
      const overlapsY =
        left.y + left.height - OVERLAP_TOLERANCE > right.y &&
        right.y + right.height - OVERLAP_TOLERANCE > left.y;
      if (overlapsX && overlapsY) {
        pairs.push([left.id, right.id]);
      }
    }
  }
  return pairs;
}

/**
 * Computes the centre of a set of cards.
 *
 * @param cards Rectangles to measure.
 * @returns The centre in flow coordinates, or `null` for an empty set.
 */
export function centerOf(cards: readonly CardRect[]): LayoutPosition | null {
  if (cards.length === 0) {
    return null;
  }
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const card of cards) {
    minX = Math.min(minX, card.x);
    minY = Math.min(minY, card.y);
    maxX = Math.max(maxX, card.x + card.width);
    maxY = Math.max(maxY, card.y + card.height);
  }
  return { x: (minX + maxX) / 2, y: (minY + maxY) / 2 };
}

/**
 * Moves a whole layout so its centre lands on a given point.
 *
 * Keeping the centre means an automatic re-layout does not throw the viewport
 * somewhere else; the cards glide into their new places around the same spot.
 *
 * @param positions Layout to shift.
 * @param sizes Measured size of each card, so the shift uses real bounds.
 * @param center Target centre in flow coordinates.
 * @returns A new map with translated positions.
 */
export function alignToCenter(
  positions: ReadonlyMap<string, LayoutPosition>,
  sizes: ReadonlyMap<string, CardSize>,
  center: LayoutPosition,
): Map<string, LayoutPosition> {
  const cards: CardRect[] = [];
  for (const [id, position] of positions) {
    const size = sizes.get(id) ?? FALLBACK_CARD_SIZE;
    cards.push({ id, x: position.x, y: position.y, ...size });
  }
  const current = centerOf(cards);
  if (current === null) {
    return new Map(positions);
  }
  const dx = Math.round(center.x - current.x);
  const dy = Math.round(center.y - current.y);
  const shifted = new Map<string, LayoutPosition>();
  for (const [id, position] of positions) {
    shifted.set(id, { x: position.x + dx, y: position.y + dy });
  }
  return shifted;
}
