import { useQuery } from '@tanstack/react-query';

import {
  fetchDiagrams,
  fetchEntities,
  fetchModel,
  fetchModels,
  fetchNodes,
  fetchRelationships,
} from './api';

/** Query keys of the semantic entity. */
export const semanticKeys = {
  all: ['semantic'] as const,
  models: () => [...semanticKeys.all, 'models'] as const,
  model: (modelId: string) => [...semanticKeys.all, 'model', modelId] as const,
  entities: (modelId: string) => [...semanticKeys.all, 'entities', modelId] as const,
  relationships: (modelId: string) => [...semanticKeys.all, 'relationships', modelId] as const,
  diagrams: (modelId: string) => [...semanticKeys.all, 'diagrams', modelId] as const,
  /** Prefix that matches the nodes of every diagram of one model. */
  allNodes: (modelId: string) => [...semanticKeys.all, 'nodes', modelId] as const,
  nodes: (modelId: string, diagramName: string) =>
    [...semanticKeys.allNodes(modelId), diagramName] as const,
};

/**
 * Lists every live model.
 *
 * @returns The query result of `GET /semantic/models`.
 */
export function useModels() {
  return useQuery({ queryKey: semanticKeys.models(), queryFn: fetchModels });
}

/**
 * Reads one model.
 *
 * @param modelId Id of the model; an empty string disables the query.
 * @returns The query result of `GET /semantic/models/{model_id}`.
 */
export function useModel(modelId: string) {
  return useQuery({
    queryKey: semanticKeys.model(modelId),
    queryFn: () => fetchModel(modelId),
    enabled: modelId !== '',
  });
}

/**
 * Lists the entities of a model.
 *
 * @param modelId Id of the model; an empty string disables the query.
 * @returns The query result of `GET .../entities`.
 */
export function useEntities(modelId: string) {
  return useQuery({
    queryKey: semanticKeys.entities(modelId),
    queryFn: () => fetchEntities(modelId),
    enabled: modelId !== '',
  });
}

/**
 * Lists the relationships of a model.
 *
 * @param modelId Id of the model; an empty string disables the query.
 * @returns The query result of `GET .../relationships`.
 */
export function useRelationships(modelId: string) {
  return useQuery({
    queryKey: semanticKeys.relationships(modelId),
    queryFn: () => fetchRelationships(modelId),
    enabled: modelId !== '',
  });
}

/**
 * Lists the diagrams of a model.
 *
 * @param modelId Id of the model; an empty string disables the query.
 * @returns The query result of `GET .../diagrams`.
 */
export function useDiagrams(modelId: string) {
  return useQuery({
    queryKey: semanticKeys.diagrams(modelId),
    queryFn: () => fetchDiagrams(modelId),
    enabled: modelId !== '',
  });
}

/**
 * Lists the nodes of one diagram.
 *
 * @param modelId Id of the model.
 * @param diagramName Name of the diagram; an empty string disables the query.
 * @returns The query result of `GET .../diagrams/{name}/nodes`.
 */
export function useNodes(modelId: string, diagramName: string) {
  return useQuery({
    queryKey: semanticKeys.nodes(modelId, diagramName),
    queryFn: () => fetchNodes(modelId, diagramName),
    enabled: modelId !== '' && diagramName !== '',
  });
}
