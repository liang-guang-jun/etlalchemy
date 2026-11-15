import { useMutation, useQueryClient } from '@tanstack/react-query';

import { ingestionKeys, startImport, type ImportRequest } from '@/entities/ingestion';
import { invalidateLater } from '@/shared/lib/refetch-later';
import { toast } from '@/shared/ui';

/**
 * Runs an import and refreshes the run history of the connection.
 *
 * The command answers only when the server finished, so the mutation stays
 * pending for the whole run; the caller renders its own progress panel.
 *
 * @param connectionId Id of the connection.
 * @returns The mutation result; its data is the finished run id.
 */
export function useStartImport(connectionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ImportRequest) => startImport(connectionId, body),
    onSuccess: async (runId) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ingestionKeys.runs(connectionId) }),
        queryClient.invalidateQueries({ queryKey: ingestionKeys.runs() }),
      ]);
      invalidateLater(queryClient, ingestionKeys.runs(connectionId));
      invalidateLater(queryClient, ingestionKeys.runs());
      invalidateLater(queryClient, ingestionKeys.run(runId));
      toast.success('Import finished');
    },
  });
}
