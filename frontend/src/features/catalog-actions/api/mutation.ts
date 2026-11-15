import { useMutation, useQueryClient } from '@tanstack/react-query';

import {
  catalogKeys,
  changeCatalog,
  createCatalog,
  discardCatalog,
  type CatalogPatch,
} from '@/entities/catalog';
import { schemaKeys } from '@/entities/schema';
import { toast } from '@/shared/ui';
import { invalidateLater } from '@/shared/lib/refetch-later';

/** Creates a catalog and refreshes the list. */
export function useCreateCatalog() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; description: string }) =>
      createCatalog(body.name, body.description),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: catalogKeys.lists() });
      invalidateLater(queryClient, catalogKeys.lists());
      toast.success('Catalog created');
    },
  });
}

/** Changes a catalog and refreshes its detail and list. */
export function useChangeCatalog(catalogId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CatalogPatch) => changeCatalog(catalogId, body),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: catalogKeys.detail(catalogId) }),
        queryClient.invalidateQueries({ queryKey: catalogKeys.lists() }),
        queryClient.invalidateQueries({ queryKey: schemaKeys.lists(catalogId) }),
      ]);
      invalidateLater(queryClient, catalogKeys.detail(catalogId));
      toast.success('Catalog updated');
    },
  });
}

/** Soft-deletes a catalog and returns to the list. */
export function useDiscardCatalog(catalogId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => discardCatalog(catalogId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: catalogKeys.lists() });
      invalidateLater(queryClient, catalogKeys.lists());
      toast.success('Catalog deleted');
    },
  });
}
