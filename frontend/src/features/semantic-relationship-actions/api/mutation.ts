import { useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query';

import {
  addRelationship,
  changeRelationship,
  removeRelationship,
  semanticKeys,
  type RelationshipCreate,
  type RelationshipPatch,
} from '@/entities/semantic';
import { invalidateLater } from '@/shared/lib/refetch-later';
import { toast } from '@/shared/ui';

/**
 * Refreshes the relationship list of a model.
 *
 * @param queryClient Client that owns the cache.
 * @param modelId Id of the model.
 */
async function refreshRelationships(queryClient: QueryClient, modelId: string): Promise<void> {
  await queryClient.invalidateQueries({ queryKey: semanticKeys.relationships(modelId) });
  invalidateLater(queryClient, semanticKeys.relationships(modelId));
}

/**
 * Adds a relationship between fields of two entities.
 *
 * @param modelId Id of the model.
 * @returns The mutation result; its data is the new relationship id.
 */
export function useAddRelationship(modelId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RelationshipCreate) => addRelationship(modelId, body),
    onSuccess: async () => {
      await refreshRelationships(queryClient, modelId);
      toast.success('Relationship added');
    },
  });
}

/**
 * Changes the attributes of a relationship.
 *
 * The inspector edits single attributes in place, so it passes
 * `notify: false`: the panel and the canvas already show the result, and a toast
 * per keystroke would only get in the way.
 *
 * @param modelId Id of the model.
 * @param relationshipId Id of the relationship.
 * @param options `notify: false` skips the success toast.
 * @returns The mutation result.
 */
export function useChangeRelationship(
  modelId: string,
  relationshipId: string,
  options: { notify?: boolean } = {},
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RelationshipPatch) => changeRelationship(modelId, relationshipId, body),
    onSuccess: async () => {
      await refreshRelationships(queryClient, modelId);
      if (options.notify !== false) {
        toast.success('Relationship updated');
      }
    },
  });
}

/**
 * Removes a relationship.
 *
 * @param modelId Id of the model.
 * @param relationshipId Id of the relationship.
 * @returns The mutation result.
 */
export function useRemoveRelationship(modelId: string, relationshipId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => removeRelationship(modelId, relationshipId),
    onSuccess: async () => {
      await refreshRelationships(queryClient, modelId);
      toast.success('Relationship deleted');
    },
  });
}
