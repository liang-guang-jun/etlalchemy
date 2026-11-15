import { useMutation, useQueryClient } from '@tanstack/react-query';

import {
  changeConnection,
  createConnection,
  discardConnection,
  ingestionKeys,
  rotateCredential,
  testConnection,
  type ConnectionCreate,
  type ConnectionPatch,
  type CredentialRotate,
} from '@/entities/ingestion';
import { invalidateLater } from '@/shared/lib/refetch-later';
import { toast } from '@/shared/ui';

/**
 * Creates a connection and refreshes the list.
 *
 * @returns The mutation result; its data is the new connection id.
 */
export function useCreateConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ConnectionCreate) => createConnection(body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ingestionKeys.connections() });
      invalidateLater(queryClient, ingestionKeys.connections());
      toast.success('Connection created');
    },
  });
}

/**
 * Changes connection metadata.
 *
 * @param connectionId Id of the connection.
 * @returns The mutation result.
 */
export function useChangeConnection(connectionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ConnectionPatch) => changeConnection(connectionId, body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ingestionKeys.connection(connectionId),
      });
      await queryClient.invalidateQueries({ queryKey: ingestionKeys.connections() });
      invalidateLater(queryClient, ingestionKeys.connection(connectionId));
      toast.success('Connection updated');
    },
  });
}

/**
 * Replaces the credential of a connection.
 *
 * @param connectionId Id of the connection.
 * @returns The mutation result.
 */
export function useRotateCredential(connectionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CredentialRotate) => rotateCredential(connectionId, body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ingestionKeys.connection(connectionId),
      });
      invalidateLater(queryClient, ingestionKeys.connection(connectionId));
      toast.success('Credential rotated');
    },
  });
}

/**
 * Probes a connection and shows the outcome as a toast.
 *
 * @param connectionId Id of the connection.
 * @returns The mutation result.
 */
export function useTestConnection(connectionId: string) {
  return useMutation({
    mutationFn: () => testConnection(connectionId),
    onSuccess: (result) => {
      if (result.ok) {
        toast.success(`Source answered in ${result.latency_ms} ms`);
      } else {
        toast.error(result.error ?? 'The source did not answer');
      }
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

/**
 * Discards a connection.
 *
 * @param connectionId Id of the connection.
 * @returns The mutation result.
 */
export function useDiscardConnection(connectionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => discardConnection(connectionId),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: ingestionKeys.connection(connectionId) });
      await queryClient.invalidateQueries({ queryKey: ingestionKeys.connections() });
      invalidateLater(queryClient, ingestionKeys.connections());
      toast.success('Connection deleted');
    },
  });
}
