import { useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query';

import {
  addEntity,
  changeEntity,
  removeEntity,
  semanticKeys,
  type EntityPatch,
} from '@/entities/semantic';
import { invalidateLater } from '@/shared/lib/refetch-later';
import { toast } from '@/shared/ui';

/**
 * Refreshes everything an entity write can touch.
 *
 * A rename rewrites the references of every relationship and the keys of every
 * node, so both are invalidated together with the entity list.
 *
 * @param queryClient Client that owns the cache.
 * @param modelId Id of the model.
 */
async function refreshEntityReads(queryClient: QueryClient, modelId: string): Promise<void> {
  await queryClient.invalidateQueries({ queryKey: semanticKeys.entities(modelId) });
  await queryClient.invalidateQueries({ queryKey: semanticKeys.relationships(modelId) });
  await queryClient.invalidateQueries({ queryKey: semanticKeys.allNodes(modelId) });
  invalidateLater(queryClient, semanticKeys.entities(modelId));
  invalidateLater(queryClient, semanticKeys.allNodes(modelId));
}

/**
 * Adds an entity backed by a catalog table.
 *
 * @param modelId Id of the model.
 * @returns The mutation result.
 */
export function useAddEntity(modelId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; table_id: string }) => addEntity(modelId, body),
    onSuccess: async () => {
      await refreshEntityReads(queryClient, modelId);
      toast.success('Entity added');
    },
  });
}

/**
 * Renames an entity and/or points it at another catalog table.
 *
 * @param modelId Id of the model.
 * @param entityName Current name of the entity.
 * @returns The mutation result.
 */
export function useChangeEntity(modelId: string, entityName: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: EntityPatch) => changeEntity(modelId, entityName, body),
    onSuccess: async () => {
      await refreshEntityReads(queryClient, modelId);
      toast.success('Entity updated');
    },
  });
}

/**
 * Removes an entity with the relationships and nodes that mention it.
 *
 * @param modelId Id of the model.
 * @param entityName Name of the entity.
 * @returns The mutation result.
 */
export function useRemoveEntity(modelId: string, entityName: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => removeEntity(modelId, entityName),
    onSuccess: async () => {
      await refreshEntityReads(queryClient, modelId);
      toast.success('Entity deleted');
    },
  });
}
