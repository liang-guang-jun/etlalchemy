import { useMutation, useQueryClient } from '@tanstack/react-query';

import { changeDomain, createDomain, discardDomain, domainKeys } from '@/entities/domain';
import { termKeys } from '@/entities/term';
import { toast } from '@/shared/ui';
import { invalidateLater } from '@/shared/lib/refetch-later';

/** Creates a domain. */
export function useCreateDomain() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; description: string }) => createDomain(body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: domainKeys.lists() });
      invalidateLater(queryClient, domainKeys.lists());
      toast.success('Domain created');
    },
  });
}

/**
 * Changes a domain.
 *
 * @param domainId Id of the domain.
 * @returns The mutation result.
 */
export function useChangeDomain(domainId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { name?: string; description?: string }) => changeDomain(domainId, body),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: domainKeys.lists() }),
        queryClient.invalidateQueries({ queryKey: domainKeys.detail(domainId) }),
      ]);
      toast.success('Domain updated');
    },
  });
}

/**
 * Discards a domain with its terms.
 *
 * @param domainId Id of the domain.
 * @returns The mutation result.
 */
export function useDiscardDomain(domainId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => discardDomain(domainId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: domainKeys.lists() }),
        queryClient.invalidateQueries({ queryKey: termKeys.all }),
      ]);
      toast.success('Domain deleted');
    },
  });
}
