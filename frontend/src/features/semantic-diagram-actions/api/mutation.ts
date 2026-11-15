import { useMutation, useQueryClient } from '@tanstack/react-query';

import {
  addDiagram,
  changeDiagram,
  moveNode,
  placeNode,
  removeDiagram,
  removeNode,
  semanticKeys,
  type Diagram,
  type DiagramCreate,
  type DiagramPatch,
  type NodeCreate,
  type NodePatch,
} from '@/entities/semantic';
import { invalidateLater } from '@/shared/lib/refetch-later';
import { toast } from '@/shared/ui';

/**
 * Adds an empty diagram to a model.
 *
 * @param modelId Id of the model.
 * @returns The mutation result.
 */
export function useAddDiagram(modelId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: DiagramCreate) => addDiagram(modelId, body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: semanticKeys.diagrams(modelId) });
      invalidateLater(queryClient, semanticKeys.diagrams(modelId));
      toast.success('Diagram added');
    },
  });
}

/**
 * Renames a diagram and/or changes its sort hint.
 *
 * @param modelId Id of the model.
 * @param name Current name of the diagram.
 * @returns The mutation result.
 */
export function useChangeDiagram(modelId: string, name: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: DiagramPatch) => changeDiagram(modelId, name, body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: semanticKeys.diagrams(modelId) });
      await queryClient.invalidateQueries({ queryKey: semanticKeys.allNodes(modelId) });
      invalidateLater(queryClient, semanticKeys.diagrams(modelId));
      toast.success('Diagram updated');
    },
  });
}

/**
 * Saves a new tab order for the diagrams of one model.
 *
 * The tab bar drags diagrams around, which needs a batch of sort hints: the
 * rows are applied optimistically and written one after another, because the
 * command changes a single diagram at a time.
 *
 * @param modelId Id of the model.
 * @returns The mutation result; its variable is the full list of new hints.
 */
export function useReorderDiagrams(modelId: string) {
  const queryClient = useQueryClient();
  const queryKey = semanticKeys.diagrams(modelId);

  return useMutation({
    mutationFn: async (rows: { name: string; order: number }[]) => {
      for (const row of rows) {
        await changeDiagram(modelId, row.name, { order: row.order });
      }
    },
    onMutate: async (rows) => {
      await queryClient.cancelQueries({ queryKey });
      const previous = queryClient.getQueryData<Diagram[]>(queryKey);
      if (previous !== undefined) {
        queryClient.setQueryData<Diagram[]>(
          queryKey,
          previous.map((diagram) => {
            const change = rows.find((row) => row.name === diagram.name);
            return change === undefined ? diagram : { ...diagram, order: change.order };
          }),
        );
      }
      return { previous };
    },
    onError: (error, _rows, context) => {
      if (context?.previous !== undefined) {
        queryClient.setQueryData(queryKey, context.previous);
      }
      toast.error(error instanceof Error ? error.message : 'Could not reorder the diagrams');
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey });
      invalidateLater(queryClient, queryKey);
    },
  });
}

/**
 * Removes a diagram with its nodes.
 *
 * @param modelId Id of the model.
 * @param name Name of the diagram.
 * @returns The mutation result.
 */
export function useRemoveDiagram(modelId: string, name: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => removeDiagram(modelId, name),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: semanticKeys.nodes(modelId, name) });
      await queryClient.invalidateQueries({ queryKey: semanticKeys.diagrams(modelId) });
      invalidateLater(queryClient, semanticKeys.diagrams(modelId));
      toast.success('Diagram deleted');
    },
  });
}

/**
 * Places an entity on the current diagram.
 *
 * @param modelId Id of the model.
 * @param diagramName Name of the diagram.
 * @returns The mutation result.
 */
export function usePlaceNode(modelId: string, diagramName: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: NodeCreate) => placeNode(modelId, diagramName, body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: semanticKeys.nodes(modelId, diagramName),
      });
      invalidateLater(queryClient, semanticKeys.nodes(modelId, diagramName));
      toast.success('Added to the diagram');
    },
  });
}

/**
 * Removes an entity from the current diagram.
 *
 * @param modelId Id of the model.
 * @param diagramName Name of the diagram.
 * @returns The mutation result.
 */
export function useRemoveNode(modelId: string, diagramName: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (entityName: string) => removeNode(modelId, diagramName, entityName),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: semanticKeys.nodes(modelId, diagramName),
      });
      invalidateLater(queryClient, semanticKeys.nodes(modelId, diagramName));
      toast.success('Removed from the diagram');
    },
  });
}

/**
 * Saves a whole auto-layout in one go.
 *
 * The writes are serialised on purpose: every `move_node` is a command on the
 * same model aggregate, so issuing them in parallel makes concurrent ones lose
 * the version check.
 *
 * @param modelId Id of the model.
 * @param diagramName Name of the diagram.
 * @returns The mutation result.
 */
export function useLayoutNodes(modelId: string, diagramName: string) {
  const queryClient = useQueryClient();
  const queryKey = semanticKeys.nodes(modelId, diagramName);

  return useMutation({
    mutationFn: async (rows: { entityName: string; x: number; y: number }[]) => {
      for (const row of rows) {
        await moveNode(modelId, diagramName, row.entityName, { x: row.x, y: row.y });
      }
    },
    onSuccess: () => {
      invalidateLater(queryClient, queryKey, 1_200);
    },
    onError: (error) => {
      void queryClient.invalidateQueries({ queryKey });
      toast.error(error instanceof Error ? error.message : 'Could not arrange the diagram');
    },
  });
}

/**
 * Saves the position of a dragged node.
 *
 * The canvas keeps the dragged position locally, so the write never refetches
 * the nodes immediately — that would snap the card back to the projected
 * position. One delayed refetch takes the eventual consistency into account.
 *
 * @param modelId Id of the model.
 * @param diagramName Name of the diagram.
 * @returns The mutation result.
 */
export function useMoveNode(modelId: string, diagramName: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ entityName, body }: { entityName: string; body: NodePatch }) =>
      moveNode(modelId, diagramName, entityName, body),
    onSuccess: () => {
      invalidateLater(queryClient, semanticKeys.nodes(modelId, diagramName), 1_200);
    },
    onError: () => {
      // A rejected move must not leave the card where the user dropped it.
      void queryClient.invalidateQueries({
        queryKey: semanticKeys.nodes(modelId, diagramName),
      });
    },
  });
}
