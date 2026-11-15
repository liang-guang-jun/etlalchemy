import type { QueryClient } from '@tanstack/react-query';

/**
 * Schedules one extra invalidation after a write.
 *
 * The read model is eventually consistent: the refetch triggered right after a
 * command can still answer with the pre-write state. One delayed refetch closes
 * that window without polling.
 *
 * @param queryClient Client that owns the cache.
 * @param queryKey Key to invalidate.
 * @param delayMs Delay before the extra refetch.
 */
export function invalidateLater(
  queryClient: QueryClient,
  queryKey: readonly unknown[],
  delayMs = 700,
): void {
  window.setTimeout(() => {
    void queryClient.invalidateQueries({ queryKey });
  }, delayMs);
}
