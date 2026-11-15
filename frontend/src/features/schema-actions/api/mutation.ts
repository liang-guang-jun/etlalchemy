import { useMutation, useQueryClient } from '@tanstack/react-query';

import { catalogKeys } from '@/entities/catalog';
import {
  changeSchema,
  createSchema,
  discardSchema,
  schemaKeys,
  type SchemaPatch,
} from '@/entities/schema';
import { toast } from '@/shared/ui';
import { invalidateLater } from '@/shared/lib/refetch-later';

/**
 * Creates a schema in a catalog.
 *
 * @param catalogId Id of the catalog.
 * @returns The mutation result.
 */
export function useCreateSchema(catalogId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; description: string }) =>
      createSchema(catalogId, body.name, body.description),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: schemaKeys.lists(catalogId) }),
        queryClient.invalidateQueries({ queryKey: catalogKeys.detail(catalogId) }),
      ]);
      invalidateLater(queryClient, schemaKeys.lists(catalogId));
      toast.success('Schema created');
    },
  });
}

/**
 * Renames a schema and refreshes the catalog tree.
 *
 * @param catalogId Id of the catalog.
 * @param schema Schema name or id.
 * @returns The mutation result.
 */
export function useChangeSchema(catalogId: string, schema: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SchemaPatch) => changeSchema(catalogId, schema, body),
    onSuccess: async (_result, variables) => {
      if (variables.name !== undefined && variables.name !== schema) {
        // The old name no longer resolves, so drop its cached detail instead of
        // refetching it (that request would answer 404).
        queryClient.removeQueries({ queryKey: schemaKeys.detail(catalogId, schema) });
      } else {
        await queryClient.invalidateQueries({ queryKey: schemaKeys.detail(catalogId, schema) });
        invalidateLater(queryClient, schemaKeys.detail(catalogId, schema));
      }
      await queryClient.invalidateQueries({ queryKey: schemaKeys.lists(catalogId) });
      invalidateLater(queryClient, schemaKeys.lists(catalogId));
      toast.success('Schema updated');
    },
  });
}

/**
 * Soft-deletes a schema.
 *
 * @param catalogId Id of the catalog.
 * @param schema Schema name or id.
 * @returns The mutation result.
 */
export function useDiscardSchema(catalogId: string, schema: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => discardSchema(catalogId, schema),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: schemaKeys.lists(catalogId) }),
        queryClient.invalidateQueries({ queryKey: catalogKeys.detail(catalogId) }),
      ]);
      invalidateLater(queryClient, schemaKeys.lists(catalogId));
      toast.success('Schema deleted');
    },
  });
}
