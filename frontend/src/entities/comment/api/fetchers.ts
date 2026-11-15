import { client } from '@/shared/api/client';

import type { TargetDescription } from '../model/target';
import { targetDescriptionSchema } from './schema';

import {
  commentCreatedSchema,
  threadCreatedSchema,
  threadDetailSchema,
  threadSchema,
  type CommentCreate,
  type CommentCreated,
  type CommentEdit,
  type Thread,
  type ThreadCreate,
  type ThreadCreated,
  type ThreadDetail,
} from './schema';

/** Filters accepted by `GET /comments/threads`. */
export interface ThreadQuery {
  /** Restricts the list to one target. */
  targetType?: string;
  /** Id of the target the threads hang off. */
  targetId?: string;
  /** Restricts the list to the threads a user started. */
  authorUserId?: string;
  /** Restricts the list to the threads a user was mentioned in. */
  mentionUserId?: string;
  /** `OPEN`, `RESOLVED` or `DISCARDED`. */
  status?: string;
  /** Maximum number of rows. */
  limit?: number;
}

/**
 * Lists the threads matching the given filters.
 *
 * @param query Filters of the request.
 * @returns The thread rows.
 */
export async function fetchThreads(query: ThreadQuery): Promise<Thread[]> {
  const response = await client.get('/comments/threads', {
    params: {
      target_type: query.targetType,
      target_id: query.targetId,
      author_user_id: query.authorUserId,
      mention_user_id: query.mentionUserId,
      status: query.status,
      limit: query.limit,
    },
  });
  return threadSchema.array().parse(response.data);
}

/**
 * Reads one thread with its comments.
 *
 * @param threadId Id of the thread.
 * @returns The thread and its comments, oldest first.
 */
export async function fetchThread(threadId: string): Promise<ThreadDetail> {
  const response = await client.get(`/comments/threads/${threadId}`);
  return threadDetailSchema.parse(response.data);
}

/**
 * Starts a thread with its first comment.
 *
 * @param body Target, optional title, body and mentions.
 * @returns The new thread and root comment ids.
 */
export async function createThread(body: ThreadCreate): Promise<ThreadCreated> {
  const response = await client.post('/comments/threads', body);
  return threadCreatedSchema.parse(response.data);
}

/**
 * Adds a comment or a reply to a thread.
 *
 * @param threadId Id of the thread.
 * @param body Body, optional parent comment and mentions.
 * @returns The new comment id, its depth and an advisory warning.
 */
export async function addComment(threadId: string, body: CommentCreate): Promise<CommentCreated> {
  const response = await client.post(`/comments/threads/${threadId}/comments`, body);
  return commentCreatedSchema.parse(response.data);
}

/**
 * Changes the body and/or mentions of a comment.
 *
 * @param threadId Id of the thread.
 * @param commentId Id of the comment.
 * @param body Fields to change.
 */
export async function editComment(
  threadId: string,
  commentId: string,
  body: CommentEdit,
): Promise<void> {
  await client.patch(`/comments/threads/${threadId}/comments/${commentId}`, body);
}

/**
 * Soft-deletes one comment.
 *
 * @param threadId Id of the thread.
 * @param commentId Id of the comment.
 */
export async function discardComment(threadId: string, commentId: string): Promise<void> {
  await client.delete(`/comments/threads/${threadId}/comments/${commentId}`);
}

/**
 * Marks a thread as resolved.
 *
 * @param threadId Id of the thread.
 */
export async function resolveThread(threadId: string): Promise<void> {
  await client.post(`/comments/threads/${threadId}/resolve`);
}

/**
 * Reopens a resolved thread.
 *
 * @param threadId Id of the thread.
 */
export async function reopenThread(threadId: string): Promise<void> {
  await client.post(`/comments/threads/${threadId}/reopen`);
}

/**
 * Soft-deletes a thread with its comments.
 *
 * @param threadId Id of the thread.
 */
export async function discardThread(threadId: string): Promise<void> {
  await client.delete(`/comments/threads/${threadId}`);
}

/** One target a caller wants described. */
export interface TargetReference {
  /** Type of the target. */
  targetType: string;
  /** Id of the target. */
  targetId: string;
}

/**
 * Describes several targets at once, e.g. the rows of the inbox.
 *
 * @param refs Targets to describe; duplicates are dropped by the backend.
 * @returns The descriptions of the targets that still exist.
 */
export async function fetchTargets(refs: readonly TargetReference[]): Promise<TargetDescription[]> {
  if (refs.length === 0) {
    return [];
  }
  const response = await client.post('/comments/targets/lookup', {
    refs: refs.map((ref) => ({ target_type: ref.targetType, target_id: ref.targetId })),
  });
  return targetDescriptionSchema.array().parse(response.data);
}

/**
 * Describes one target.
 *
 * @param targetType Type of the target.
 * @param targetId Id of the target.
 * @returns The description of the target.
 */
export async function fetchTarget(
  targetType: string,
  targetId: string,
): Promise<TargetDescription> {
  const response = await client.get(
    `/comments/targets/${encodeURIComponent(targetType)}/${encodeURIComponent(targetId)}`,
  );
  return targetDescriptionSchema.parse(response.data);
}
