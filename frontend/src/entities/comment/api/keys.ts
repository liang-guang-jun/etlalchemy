import type { ThreadQuery } from './fetchers';

/** Query keys of the comment entity. */
export const commentKeys = {
  all: ['comment'] as const,
  threads: (query: ThreadQuery) => [...commentKeys.all, 'threads', query] as const,
  thread: (threadId: string) => [...commentKeys.all, 'thread', threadId] as const,
  target: (targetType: string, targetId: string) =>
    [...commentKeys.all, 'target', targetType, targetId] as const,
  targets: (keys: readonly string[]) => [...commentKeys.all, 'targets', keys] as const,
};
