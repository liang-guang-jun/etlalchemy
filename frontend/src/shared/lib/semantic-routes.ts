/** Name of the diagram every model owns and always shows every entity. */
export const ALL_DIAGRAM = 'All';

/** Path of the semantic model list. */
export const MODELS_PATH = '/semantic';

/**
 * Builds the path of one model workspace.
 *
 * @param modelId Id of the model.
 * @returns The workspace path, without any query string.
 */
export function modelPath(modelId: string): string {
  return `${MODELS_PATH}/${encodeURIComponent(modelId)}`;
}

/** Canvas selection carried by a workspace URL. */
export interface WorkspaceState {
  diagram?: string;
  entity?: string;
  relationship?: string;
}

/**
 * Builds a workspace path with the diagram and the current selection.
 *
 * The three values live in the query string so a workspace view can be
 * bookmarked and shared; empty values are dropped.
 *
 * @param modelId Id of the model.
 * @param state Diagram name and selection to encode.
 * @returns The workspace path with its query string.
 */
export function workspacePath(modelId: string, state: WorkspaceState = {}): string {
  const params = new URLSearchParams();
  for (const key of ['diagram', 'entity', 'relationship'] as const) {
    const value = state[key];
    if (value !== undefined && value !== '') {
      params.set(key, value);
    }
  }
  const query = params.toString();
  return query === '' ? modelPath(modelId) : `${modelPath(modelId)}?${query}`;
}

/**
 * Reads the diagram and selection of a workspace query string.
 *
 * @param search Query string, with or without its leading question mark.
 * @returns The decoded values, with the missing ones left `undefined`.
 */
export function parseWorkspaceSearch(search: string): WorkspaceState {
  const params = new URLSearchParams(search);
  const read = (key: string): string | undefined => {
    const value = params.get(key);
    return value === null || value === '' ? undefined : value;
  };
  return {
    diagram: read('diagram'),
    entity: read('entity'),
    relationship: read('relationship'),
  };
}

/**
 * Reads the diagram a model opened last, as remembered by this browser.
 *
 * @param modelId Id of the model.
 * @returns The stored diagram name, or `undefined`.
 */
export function readLastDiagram(modelId: string): string | undefined {
  const value = window.localStorage.getItem(`semantic:lastDiagram:${modelId}`);
  return value === null || value === '' ? undefined : value;
}

/**
 * Remembers the diagram a model opened last.
 *
 * @param modelId Id of the model.
 * @param diagramName Name of the diagram.
 */
export function writeLastDiagram(modelId: string, diagramName: string): void {
  window.localStorage.setItem(`semantic:lastDiagram:${modelId}`, diagramName);
}

/**
 * Forgets the diagram a model opened last, e.g. after the model was discarded.
 *
 * @param modelId Id of the model.
 */
export function clearLastDiagram(modelId: string): void {
  window.localStorage.removeItem(`semantic:lastDiagram:${modelId}`);
}
