import type { Viewport } from '@xyflow/react';

/**
 * Storage key of one cached canvas viewport.
 *
 * @param modelId Id of the model.
 * @param diagramName Name of the diagram.
 * @returns The localStorage key.
 */
function viewportKey(modelId: string, diagramName: string): string {
  return `semantic:viewport:${modelId}:${diagramName}`;
}

/**
 * Reads the cached zoom and pan of a diagram.
 *
 * @param modelId Id of the model.
 * @param diagramName Name of the diagram.
 * @returns The cached viewport, or `null` when the canvas was never moved.
 */
export function loadViewport(modelId: string, diagramName: string): Viewport | null {
  const raw = window.localStorage.getItem(viewportKey(modelId, diagramName));
  if (raw === null) {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === 'object' &&
      parsed !== null &&
      typeof (parsed as Viewport).x === 'number' &&
      typeof (parsed as Viewport).y === 'number' &&
      typeof (parsed as Viewport).zoom === 'number'
    ) {
      return parsed as Viewport;
    }
  } catch {
    // A corrupted entry must not break the canvas.
  }
  return null;
}

/**
 * Caches the zoom and pan of a diagram for the next visit.
 *
 * @param modelId Id of the model.
 * @param diagramName Name of the diagram.
 * @param viewport Viewport to remember.
 */
export function saveViewport(modelId: string, diagramName: string, viewport: Viewport): void {
  window.localStorage.setItem(viewportKey(modelId, diagramName), JSON.stringify(viewport));
}
