import { useMutation, useQueryClient } from '@tanstack/react-query';

import { addField, changeField, discardField, fieldKeys, renameField } from '@/entities/field';
import { toast } from '@/shared/ui';
import { invalidateLater } from '@/shared/lib/refetch-later';

interface FieldTarget {
  catalogId: string;
  schema: string;
  table: string;
}

/**
 * Adds a field to a table.
 *
 * @param target Location of the table.
 * @returns The mutation result.
 */
export function useAddField(target: FieldTarget) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; dataType: string; nullable: boolean }) =>
      addField(
        target.catalogId,
        target.schema,
        target.table,
        body.name,
        body.dataType,
        body.nullable,
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: fieldKeys.list(target.catalogId, target.schema, target.table),
      });
      invalidateLater(queryClient, fieldKeys.list(target.catalogId, target.schema, target.table));
      toast.success('Field added');
    },
  });
}

/**
 * Changes the type and/or nullability of a field.
 *
 * @param target Location of the table.
 * @returns The mutation result.
 */
export function useChangeField(target: FieldTarget) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { fieldName: string; data_type?: string; nullable?: boolean }) =>
      changeField(target.catalogId, target.schema, target.table, body.fieldName, {
        data_type: body.data_type,
        nullable: body.nullable,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: fieldKeys.list(target.catalogId, target.schema, target.table),
      });
      invalidateLater(queryClient, fieldKeys.list(target.catalogId, target.schema, target.table));
      toast.success('Field updated');
    },
  });
}

/**
 * Removes a field from a table.
 *
 * @param target Location of the table.
 * @returns The mutation result.
 */
export function useDiscardField(target: FieldTarget) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (fieldName: string) =>
      discardField(target.catalogId, target.schema, target.table, fieldName),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: fieldKeys.list(target.catalogId, target.schema, target.table),
      });
      invalidateLater(queryClient, fieldKeys.list(target.catalogId, target.schema, target.table));
      toast.success('Field deleted');
    },
  });
}

/**
 * Renames a field.
 *
 * @param target Location of the table.
 * @returns The mutation result.
 */
export function useRenameField(target: FieldTarget) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { fieldName: string; newName: string }) =>
      renameField(target.catalogId, target.schema, target.table, body.fieldName, body.newName),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: fieldKeys.list(target.catalogId, target.schema, target.table),
      });
      invalidateLater(queryClient, fieldKeys.list(target.catalogId, target.schema, target.table));
      toast.success('Field renamed');
    },
  });
}
