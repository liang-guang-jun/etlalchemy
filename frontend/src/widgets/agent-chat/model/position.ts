import { clampToViewport } from '@/shared/lib/floating-placement';

/** Key the widget position is persisted under. */
export const WIDGET_POSITION_KEY = 'etlalchemy.agent.widget-position';

/** Key the panel size is persisted under. */
export const PANEL_SIZE_KEY = 'etlalchemy.agent.panel-size';

/** Square size of the floating button. */
export const WIDGET_SIZE = 56;

/** Width the panel opens with, before the reader resizes it. */
const DEFAULT_PANEL_WIDTH = 400;

/** Height the panel opens with, before the reader resizes it. */
const DEFAULT_PANEL_HEIGHT = 600;

/** Fraction of the viewport width the panel never shrinks below. */
const MIN_WIDTH_RATIO = 0.25;

/** Floor that keeps the panel readable on a narrow screen. */
const MIN_PANEL_WIDTH = 320;

/** Floor that keeps a usable message, composer and header inside the panel. */
const MIN_PANEL_HEIGHT = 320;

/** Distance kept from the viewport edges. */
const EDGE = 24;

/** A stored position, in viewport coordinates. */
export interface WidgetPosition {
  x: number;
  y: number;
}

/** Size of the floating panel. */
export interface PanelSize {
  width: number;
  height: number;
}

/**
 * Returns the smallest size the panel may take.
 *
 * The width floor is a quarter of the viewport, so the dialog is never a narrow
 * column on a wide screen while staying readable on a phone.
 *
 * @param viewport Current viewport size.
 * @returns The minimum width and height.
 */
export function minimumPanelSize(viewport: { width: number; height: number }): PanelSize {
  return {
    width: Math.max(MIN_PANEL_WIDTH, Math.round(viewport.width * MIN_WIDTH_RATIO)),
    height: MIN_PANEL_HEIGHT,
  };
}

/**
 * Clamps a requested panel size into the limits of the current viewport.
 *
 * @param size Requested size.
 * @param viewport Current viewport size.
 * @returns The size to render, never larger than the viewport minus one edge.
 */
export function clampPanelSize(
  size: PanelSize,
  viewport: { width: number; height: number },
): PanelSize {
  const minimum = minimumPanelSize(viewport);
  return {
    width: Math.max(minimum.width, Math.min(Math.round(size.width), viewport.width - EDGE)),
    height: Math.max(minimum.height, Math.min(Math.round(size.height), viewport.height - EDGE)),
  };
}

/**
 * Reads the stored panel size, clamped to the current viewport.
 *
 * @param storage Storage to read from; defaults to `localStorage`.
 * @param viewport Current viewport size.
 * @returns The size to render the panel at.
 */
export function readPanelSize(
  storage: Storage | undefined = globalThis.localStorage,
  viewport: { width: number; height: number } = {
    width: globalThis.innerWidth,
    height: globalThis.innerHeight,
  },
): PanelSize {
  const fallback = { width: DEFAULT_PANEL_WIDTH, height: DEFAULT_PANEL_HEIGHT };
  const raw = storage?.getItem(PANEL_SIZE_KEY) ?? null;
  if (raw === null) {
    return clampPanelSize(fallback, viewport);
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      parsed !== null &&
      typeof parsed === 'object' &&
      typeof (parsed as PanelSize).width === 'number' &&
      typeof (parsed as PanelSize).height === 'number'
    ) {
      return clampPanelSize(parsed as PanelSize, viewport);
    }
  } catch {
    // A corrupted entry falls back to the default size.
  }
  return clampPanelSize(fallback, viewport);
}

/**
 * Persists the size of the floating panel.
 *
 * @param size Size to store.
 * @param storage Storage to write to; defaults to `localStorage`.
 */
export function writePanelSize(
  size: PanelSize,
  storage: Storage | undefined = globalThis.localStorage,
): void {
  try {
    storage?.setItem(PANEL_SIZE_KEY, JSON.stringify(size));
  } catch {
    // Ignore: the panel still works without persistence.
  }
}

/**
 * Reads the stored position, falling back to the bottom-right corner.
 *
 * A stored position is clamped to the current viewport, so a window that shrank
 * since the last visit never leaves the button off screen.
 *
 * @param storage Storage to read from; defaults to `localStorage`.
 * @param viewport Current viewport size.
 * @returns The position to render the button at.
 */
export function readWidgetPosition(
  storage: Storage | undefined = globalThis.localStorage,
  viewport: { width: number; height: number } = {
    width: globalThis.innerWidth,
    height: globalThis.innerHeight,
  },
): WidgetPosition {
  const fallback = {
    x: viewport.width - WIDGET_SIZE - EDGE,
    y: viewport.height - WIDGET_SIZE - EDGE,
  };
  const raw = storage?.getItem(WIDGET_POSITION_KEY) ?? null;
  if (raw === null) {
    return clampToViewport(fallback, WIDGET_SIZE, viewport);
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      parsed !== null &&
      typeof parsed === 'object' &&
      typeof (parsed as WidgetPosition).x === 'number' &&
      typeof (parsed as WidgetPosition).y === 'number'
    ) {
      return clampToViewport(
        { x: (parsed as WidgetPosition).x, y: (parsed as WidgetPosition).y },
        WIDGET_SIZE,
        viewport,
      );
    }
  } catch {
    // A corrupted entry falls back to the default corner.
  }
  return clampToViewport(fallback, WIDGET_SIZE, viewport);
}

/**
 * Persists the position of the floating button.
 *
 * Storage failures (private mode, quota) are swallowed: the position is a
 * comfort feature and must never break the widget.
 *
 * @param position Position to store.
 * @param storage Storage to write to; defaults to `localStorage`.
 */
export function writeWidgetPosition(
  position: WidgetPosition,
  storage: Storage | undefined = globalThis.localStorage,
): void {
  try {
    storage?.setItem(WIDGET_POSITION_KEY, JSON.stringify(position));
  } catch {
    // Ignore: the widget still works without persistence.
  }
}
