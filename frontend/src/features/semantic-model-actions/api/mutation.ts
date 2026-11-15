import { useMutation, useQueryClient } from '@tanstack/react-query';

import {
  changeModel,
  createModel,
  discardModel,
  semanticKeys,
  type ModelCreate,
  type ModelPatch,
} from '@/entities/semantic';
import { invalidateLater } from '@/shared/lib/refetch-later';
import { toast } from '@/shared/ui';

/**
 * Creates a model and refreshes the list.
 *
 * @returns The mutation result; its data is the new model id.
 */
export function useCreateModel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ModelCreate) => createModel(body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: semanticKeys.models() });
      invalidateLater(queryClient, semanticKeys.models());
      toast.success('Model created');
    },
  });
}

/**
 * Changes the name and/or description of a model.
 *
 * @param modelId Id of the model.
 * @returns The mutation result.
 */
export function useChangeModel(modelId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ModelPatch) => changeModel(modelId, body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: semanticKeys.model(modelId) });
      await queryClient.invalidateQueries({ queryKey: semanticKeys.models() });
      invalidateLater(queryClient, semanticKeys.model(modelId));
      toast.success('Model updated');
    },
  });
}

/**
 * Discards a model with everything it owned.
 *
 * @param modelId Id of the model.
 * @returns The mutation result.
 */
export function useDiscardModel(modelId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => discardModel(modelId),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: semanticKeys.model(modelId) });
      queryClient.removeQueries({ queryKey: semanticKeys.entities(modelId) });
      queryClient.removeQueries({ queryKey: semanticKeys.relationships(modelId) });
      queryClient.removeQueries({ queryKey: semanticKeys.diagrams(modelId) });
      queryClient.removeQueries({ queryKey: semanticKeys.allNodes(modelId) });
      await queryClient.invalidateQueries({ queryKey: semanticKeys.models() });
      invalidateLater(queryClient, semanticKeys.models());
      toast.success('Model deleted');
    },
  });
}
