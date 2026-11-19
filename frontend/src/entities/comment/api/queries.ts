import { useQueries, useQuery } from '@tanstack/react-query';

import {
  fetchTarget,
  fetchTargets,
  fetchThread,
  fetchThreads,
  type TargetReference,
  type ThreadQuery,
} from './fetchers';
import { commentKeys } from './keys';

/**
 * Lists the threads matching the given filters.
 *
 * @param query Filters of the request; the key follows the whole filter set.
 * @param enabled Whether the caller wants the request at all.
 * @returns The query result of `GET /comments/threads`.
 */
export function useThreads(query: ThreadQuery, enabled = true) {
  return useQuery({
    queryKey: commentKeys.threads(query),
    queryFn: () => fetchThreads(query),
    enabled: enabled && (query.targetId === undefined || query.targetId !== ''),
  });
}

/**
 * Reads one thread with its comments.
 *
 * @param threadId Id of the thread; an empty string disables the query.
 * @returns The query result of `GET /comments/threads/{thread_id}`.
 */
export function useThread(threadId: string) {
  return useQuery({
    queryKey: commentKeys.thread(threadId),
    queryFn: () => fetchThread(threadId),
    enabled: threadId !== '',
  });
}

/**
 * Counts the open threads of one target.
 *
 * @param targetType Type of the target.
 * @param targetId Id of the target; an empty string disables the query.
 * @returns The number of open threads, or `0` while it is unknown.
 */
export function useOpenThreadCount(targetType: string, targetId: string): number {
  const threads = useThreads({ targetType, targetId, status: 'OPEN' }, targetId !== '');
  return (threads.data ?? []).length;
}

/**
 * Describes the targets of a list, e.g. the rows of the inbox.
 *
 * The key is the sorted set of references, so two lists with the same targets
 * share one request whatever order they arrive in. The lookup only supplies the
 * display name of an object, so a failure stays silent: the caller renders the
 * shortened id instead, which is exactly what it shows while the query loads.
 *
 * @param refs Targets to describe.
 * @returns The query result of `POST /comments/targets/lookup`.
 */
export function useTargets(refs: readonly TargetReference[]) {
  const keys = refs.map((ref) => `${ref.targetType}:${ref.targetId}`).sort();
  return useQuery({
    queryKey: [...commentKeys.all, 'targets', keys],
    queryFn: () => fetchTargets(refs),
    enabled: refs.length > 0,
    meta: { silent: true },
  });
}

/**
 * Describes one target.
 *
 * @param targetType Type of the target; an empty string disables the query.
 * @param targetId Id of the target.
 * @returns The query result of `GET /comments/targets/{type}/{id}`.
 */
export function useTarget(targetType: string, targetId: string) {
  return useQuery({
    queryKey: commentKeys.target(targetType, targetId),
    queryFn: () => fetchTarget(targetType, targetId),
    enabled: targetType !== '' && targetId !== '',
  });
}

/**
 * Loads the comments of several threads at once.
 *
 * The panel only runs this while a search term is typed, so filtering by a
 * comment body does not cost one request per row the rest of the time.
 *
 * @param threadIds Ids of the threads to load, in display order.
 * @param enabled Whether the caller wants the requests at all.
 * @returns The details in the given order, `undefined` where still loading.
 */
export function useThreadDetails(threadIds: readonly string[], enabled = true) {
  return useQueries({
    queries: threadIds.map((threadId) => ({
      queryKey: commentKeys.thread(threadId),
      queryFn: () => fetchThread(threadId),
      enabled,
    })),
    combine: (results) => results.map((result) => result.data),
  });
}
