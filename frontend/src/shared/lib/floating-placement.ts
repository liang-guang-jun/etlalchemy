/** Axis-aligned rectangle in viewport coordinates. */
export interface Box {
  /** Distance from the left viewport edge. */
  x: number;
  /** Distance from the top viewport edge. */
  y: number;
  /** Width in pixels. */
  width: number;
  /** Height in pixels. */
  height: number;
}

/** Side of the anchor the panel opens towards. */
export type PanelSide = 'top' | 'bottom' | 'left' | 'right';

/** Resolved position of a floating panel. */
export interface PanelPlacement {
  /** Distance from the left viewport edge; never negative in the result. */
  left: number;
  /** Distance from the top viewport edge; never negative in the result. */
  top: number;
  /** Side the panel opens towards, used for the transform origin. */
  side: PanelSide;
}

/** Gap between the anchor and the panel. */
const GAP = 12;

/** Distance kept between the panel and every viewport edge. */
const MARGIN = 12;

/** Fraction of the viewport height that counts as the top band. */
const TOP_BAND = 0.3;

/** Fraction of the viewport height above which the anchor sits in the bottom band. */
const BOTTOM_BAND = 0.6;

/**
 * Keeps a coordinate inside `[MARGIN, limit - size - MARGIN]`.
 *
 * When the panel is taller or wider than the viewport the lower bound wins, so
 * the top-left of the panel stays reachable.
 *
 * @param value Desired coordinate.
 * @param size Size of the panel along that axis.
 * @param limit Viewport size along that axis.
 * @returns The clamped coordinate.
 */
function clamp(value: number, size: number, limit: number): number {
  return Math.max(MARGIN, Math.min(value, limit - size - MARGIN));
}

/**
 * Places a floating panel next to an anchor inside the viewport.
 *
 * The anchor's vertical position picks the direction first — a widget dragged
 * to the top opens downwards, one dragged to the bottom opens upwards — and an
 * anchor in the middle band opens sideways, to the right when there is room.
 * The result is clamped to the viewport so a panel never leaves the screen.
 *
 * @param anchor Rectangle of the trigger.
 * @param panel Size of the panel.
 * @param viewport Size of the visible area.
 * @returns The clamped placement and the side it opens towards.
 */
export function placePanel(anchor: Box, panel: Box, viewport: Box): PanelPlacement {
  const anchorCenter = anchor.y + anchor.height / 2;
  const opensDown = anchorCenter + panel.height + GAP + MARGIN <= viewport.height;
  const opensUp = anchorCenter - panel.height - GAP - MARGIN >= 0;

  let side: PanelSide;
  let left: number;
  let top: number;

  if (anchorCenter < viewport.height * TOP_BAND && opensDown) {
    side = 'bottom';
    left = anchor.x + anchor.width / 2 - panel.width / 2;
    top = anchor.y + anchor.height + GAP;
  } else if (anchorCenter > viewport.height * BOTTOM_BAND && opensUp) {
    side = 'top';
    left = anchor.x + anchor.width / 2 - panel.width / 2;
    top = anchor.y - panel.height - GAP;
  } else {
    const roomRight = anchor.x + anchor.width + GAP + panel.width + MARGIN <= viewport.width;
    side = roomRight || anchor.x < viewport.width / 2 ? 'right' : 'left';
    left = side === 'right' ? anchor.x + anchor.width + GAP : anchor.x - panel.width - GAP;
    top = anchorCenter - panel.height / 2;
  }

  return {
    side,
    left: clamp(left, panel.width, viewport.width),
    top: clamp(top, panel.height, viewport.height),
  };
}

/**
 * Keeps a dragged icon fully inside the viewport.
 *
 * @param position Top-left corner of the icon.
 * @param size Square size of the icon.
 * @param viewport Size of the visible area.
 * @returns The position clamped to the viewport.
 */
export function clampToViewport(
  position: { x: number; y: number },
  size: number,
  viewport: { width: number; height: number },
): { x: number; y: number } {
  return {
    x: Math.max(0, Math.min(position.x, viewport.width - size)),
    y: Math.max(0, Math.min(position.y, viewport.height - size)),
  };
}
