import { useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query';

import {
  addComment,
  commentKeys,
  createThread,
  discardComment,
  discardThread,
  editComment,
  reopenThread,
  resolveThread,
  type CommentCreate,
  type CommentEdit,
  type ThreadCreate,
} from '@/entities/comment';
import { normalizeError } from '@/shared/api/error';
import { invalidateLater } from '@/shared/lib/refetch-later';
import { toast } from '@/shared/ui';

/**
 * Refreshes every comment query.
 *
 * The read model is eventually consistent, so the immediate invalidation is
 * followed by one delayed refetch.
 *
 * @param queryClient Client that owns the cache.
 */
async function invalidateComments(queryClient: QueryClient): Promise<void> {
  await queryClient.invalidateQueries({ queryKey: commentKeys.all });
  invalidateLater(queryClient, commentKeys.all);
}

/**
 * Reports a failed comment command.
 *
 * An unknown mention and a permission problem are two failures users actually
 * hit, so they get a dedicated message instead of the raw backend text.
 *
 * @param error Value thrown by the mutation.
 */
function reportError(error: unknown): void {
  const normalized = normalizeError(error);
  if (normalized.kind === 'not_found' && normalized.detail.toLowerCase().includes('user')) {
    toast.error('The mentioned user does not exist');
    return;
  }
  if (normalized.kind === 'forbidden') {
    toast.error('You are not allowed to change this discussion');
    return;
  }
  toast.error(normalized.detail);
}

/**
 * Starts a thread on a target.
 *
 * @returns The mutation result, holding the new thread and root comment ids.
 */
export function useCreateThread() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ThreadCreate) => createThread(body),
    onSuccess: async () => {
      await invalidateComments(queryClient);
      toast.success('Discussion started');
    },
    onError: reportError,
  });
}

/**
 * Posts a comment or a reply.
 *
 * The response carries `depth_warning`, which the panel shows above the editor;
 * it stays on `mutation.data` until the next submission.
 *
 * @param threadId Id of the thread.
 * @returns The mutation result.
 */
export function useAddComment(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CommentCreate) => addComment(threadId, body),
    onSuccess: async () => {
      await invalidateComments(queryClient);
    },
    onError: reportError,
  });
}

/**
 * Changes the body and mentions of a comment.
 *
 * @param threadId Id of the thread.
 * @param commentId Id of the comment.
 * @returns The mutation result.
 */
export function useEditComment(threadId: string, commentId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CommentEdit) => editComment(threadId, commentId, body),
    onSuccess: async () => {
      await invalidateComments(queryClient);
      toast.success('Comment updated');
    },
    onError: reportError,
  });
}

/**
 * Soft-deletes one comment.
 *
 * @param threadId Id of the thread.
 * @returns The mutation result, called with the comment id.
 */
export function useDiscardComment(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (commentId: string) => discardComment(threadId, commentId),
    onSuccess: async () => {
      await invalidateComments(queryClient);
      toast.success('Comment deleted');
    },
    onError: reportError,
  });
}

/**
 * Marks a thread as resolved.
 *
 * @returns The mutation result, called with the thread id.
 */
export function useResolveThread() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (threadId: string) => resolveThread(threadId),
    onSuccess: async () => {
      await invalidateComments(queryClient);
      toast.success('Discussion resolved');
    },
    onError: reportError,
  });
}

/**
 * Reopens a resolved thread.
 *
 * @returns The mutation result, called with the thread id.
 */
export function useReopenThread() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (threadId: string) => reopenThread(threadId),
    onSuccess: async () => {
      await invalidateComments(queryClient);
      toast.success('Discussion reopened');
    },
    onError: reportError,
  });
}

/**
 * Soft-deletes a thread with its comments.
 *
 * @returns The mutation result, called with the thread id.
 */
export function useDiscardThread() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (threadId: string) => discardThread(threadId),
    onSuccess: async () => {
      await invalidateComments(queryClient);
      toast.success('Discussion deleted');
    },
    onError: reportError,
  });
}
