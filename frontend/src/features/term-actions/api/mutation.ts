import { useMutation, useQueryClient } from '@tanstack/react-query';

import {
  changeTerm,
  createTerm,
  discardTerm,
  linkTerm,
  moveTerm,
  termKeys,
  transitionTerm,
  unlinkTerm,
  type TermTransition,
} from '@/entities/term';
import { toast } from '@/shared/ui';
import { invalidateLater } from '@/shared/lib/refetch-later';

/**
 * Refreshes every term query, active or not.
 *
 * A link changes the term detail and the linked-terms list of a catalog object,
 * and both are on screen at the same time, so every cached list is refetched
 * right away; the delayed pass covers the read model that is still catching up.
 *
 * @param queryClient Client that owns the cache.
 */
async function invalidateTerms(queryClient: ReturnType<typeof useQueryClient>): Promise<void> {
  await queryClient.invalidateQueries({ queryKey: termKeys.all, refetchType: 'all' });
  invalidateLater(queryClient, termKeys.all);
}

/**
 * Creates a term.
 *
 * @param domainId Id of the domain.
 * @returns The mutation result.
 */
export function useCreateTerm(domainId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      name: string;
      definition: string;
      aliases: string[];
      parent: string | null;
      color: string;
    }) => createTerm(domainId, body),
    onSuccess: async () => {
      await invalidateTerms(queryClient);
      toast.success('Term created');
    },
  });
}

/**
 * Changes a term.
 *
 * @param domainId Id of the domain.
 * @param termId Id of the term.
 * @returns The mutation result.
 */
export function useChangeTerm(domainId: string, termId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      name?: string;
      definition?: string;
      aliases_add?: string[];
      aliases_remove?: string[];
      color?: string;
    }) => changeTerm(domainId, termId, body),
    onSuccess: async () => {
      await invalidateTerms(queryClient);
      toast.success('Term updated');
    },
  });
}

/**
 * Moves a term under another parent.
 *
 * @param domainId Id of the domain.
 * @returns The mutation result.
 */
export function useMoveTerm(domainId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { termId: string; newParent: string | null }) =>
      moveTerm(domainId, body.termId, body.newParent),
    onSuccess: async () => {
      await invalidateTerms(queryClient);
      toast.success('Term moved');
    },
  });
}

/**
 * Applies a lifecycle command to a term.
 *
 * @param domainId Id of the domain.
 * @returns The mutation result.
 */
export function useTransitionTerm(domainId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { termId: string; transition: TermTransition; argument: string }) =>
      transitionTerm(domainId, body.termId, body.transition, body.argument),
    onSuccess: async () => {
      await invalidateTerms(queryClient);
      toast.success('Term status updated');
    },
  });
}

/**
 * Discards a term and its descendants.
 *
 * @param domainId Id of the domain.
 * @returns The mutation result.
 */
export function useDiscardTerm(domainId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (termId: string) => discardTerm(domainId, termId),
    onSuccess: async () => {
      await invalidateTerms(queryClient);
      toast.success('Term deleted');
    },
  });
}

/**
 * Links a term to a catalog object or to one of its fields.
 *
 * @param domainId Id of the domain.
 * @param termId Id of the term.
 * @returns The mutation result.
 */
export function useLinkTerm(domainId: string, termId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { target_id: string; target_kind: string; field_name?: string }) =>
      linkTerm(domainId, termId, body),
    onSuccess: async () => {
      await invalidateTerms(queryClient);
      toast.success('Term link added');
    },
  });
}

/**
 * Removes a catalog link from a term.
 *
 * @param domainId Id of the domain.
 * @param termId Id of the term.
 * @returns The mutation result.
 */
export function useUnlinkTerm(domainId: string, termId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { target_id: string; target_kind: string; field_name?: string }) =>
      unlinkTerm(domainId, termId, body),
    onSuccess: async () => {
      await invalidateTerms(queryClient);
      toast.success('Link removed');
    },
  });
}
