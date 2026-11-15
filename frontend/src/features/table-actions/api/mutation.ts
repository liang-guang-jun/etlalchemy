import { useMutation, useQueryClient } from '@tanstack/react-query';

import { schemaKeys } from '@/entities/schema';
import {
  changeTable,
  createTable,
  discardTable,
  tableKeys,
  type TablePatch,
} from '@/entities/table';
import { toast } from '@/shared/ui';
import { invalidateLater } from '@/shared/lib/refetch-later';

/**
 * Creates a table in a schema.
 *
 * @param catalogId Id of the catalog.
 * @param schema Schema name or id.
 * @returns The mutation result.
 */
export function useCreateTable(catalogId: string, schema: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (tableName: string) => createTable(catalogId, schema, tableName),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: tableKeys.lists(catalogId, schema) }),
        queryClient.invalidateQueries({ queryKey: schemaKeys.lists(catalogId) }),
      ]);
      invalidateLater(queryClient, tableKeys.lists(catalogId, schema));
      toast.success('Table created');
    },
  });
}

/**
 * Changes a table name and/or description.
 *
 * @param catalogId Id of the catalog.
 * @param schema Schema name or id.
 * @param table Table name or id.
 * @returns The mutation result.
 */
export function useChangeTable(catalogId: string, schema: string, table: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (patch: TablePatch) => changeTable(catalogId, schema, table, patch),
    onSuccess: async (_result, variables) => {
      if (variables.name !== undefined && variables.name !== table) {
        // A rename makes the old name unresolvable, so drop its cached detail
        // instead of refetching it (that request would answer 404).
        queryClient.removeQueries({ queryKey: tableKeys.detail(catalogId, schema, table) });
      } else {
        await queryClient.invalidateQueries({
          queryKey: tableKeys.detail(catalogId, schema, table),
        });
        invalidateLater(queryClient, tableKeys.detail(catalogId, schema, table));
      }
      await queryClient.invalidateQueries({ queryKey: tableKeys.lists(catalogId, schema) });
      invalidateLater(queryClient, tableKeys.lists(catalogId, schema));
      toast.success('Table updated');
    },
  });
}

/**
 * Soft-deletes a table.
 *
 * @param catalogId Id of the catalog.
 * @param schema Schema name or id.
 * @param table Table name or id.
 * @returns The mutation result.
 */
export function useDiscardTable(catalogId: string, schema: string, table: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => discardTable(catalogId, schema, table),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: tableKeys.lists(catalogId, schema) }),
        queryClient.invalidateQueries({ queryKey: schemaKeys.lists(catalogId) }),
      ]);
      invalidateLater(queryClient, tableKeys.lists(catalogId, schema));
      toast.success('Table deleted');
    },
  });
}
