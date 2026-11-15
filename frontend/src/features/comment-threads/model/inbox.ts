import { useMemo } from 'react';

import { useThreads } from '@/entities/comment';
import { useSessionStore } from '@/entities/session';

/**
 * Counts the open threads the signed-in user started or was mentioned in.
 *
 * Both lists are read separately because the API takes one filter at a time;
 * the union is what the top-bar badge shows.
 *
 * @returns Number of open threads that concern the current user.
 */
export function useMyOpenThreadCount(): number {
  const currentUserId = useSessionStore((state) => state.userId) ?? '';
  const enabled = currentUserId !== '';
  const mine = useThreads({ status: 'OPEN', authorUserId: currentUserId }, enabled);
  const mentions = useThreads({ status: 'OPEN', mentionUserId: currentUserId }, enabled);

  return useMemo(() => {
    const ids = new Set<string>();
    for (const thread of mine.data ?? []) {
      ids.add(thread.thread_id);
    }
    for (const thread of mentions.data ?? []) {
      ids.add(thread.thread_id);
    }
    return ids.size;
  }, [mine.data, mentions.data]);
}
