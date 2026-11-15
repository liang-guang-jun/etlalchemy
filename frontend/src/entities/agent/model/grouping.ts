import { parseTimestamp } from '@/shared/lib/timestamp';

/** One bucket of the conversation list. */
export interface ConversationGroup<T> {
  /** Heading shown above the bucket. */
  label: string;
  /** Conversations of the bucket, most recent first. */
  items: T[];
}

/** Heading of the current day bucket. */
const TODAY = 'Today';

/** Heading of the previous day bucket. */
const YESTERDAY = 'Yesterday';

/** Heading of the last week bucket. */
const LAST_WEEK = 'Previous 7 Days';

/** Heading of everything older. */
const OLDER = 'Older';

/** Length of a day in milliseconds. */
const DAY_MS = 86_400_000;

/**
 * Counts whole calendar days between two moments.
 *
 * Midnight is taken from the local timezone, so a message sent at 23:59 and one
 * read at 00:01 fall into different buckets.
 *
 * @param iso ISO timestamp to place.
 * @param now Reference moment.
 * @returns `0` for today, `1` for yesterday, and so on.
 */
function dayOffset(iso: string, now: Date): number {
  const date = parseTimestamp(iso);
  if (date === null) {
    return Number.POSITIVE_INFINITY;
  }
  const startOfNow = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const startOfDate = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  return Math.round((startOfNow - startOfDate) / DAY_MS);
}

/**
 * Buckets conversations into Today, Yesterday, Previous 7 Days and Older.
 *
 * Empty buckets are omitted so the sidebar never shows a bare heading, and
 * every bucket is sorted by its most recent activity.
 *
 * @param conversations Conversations to bucket; the input is not mutated.
 * @param now Reference moment, injectable for tests.
 * @returns The non-empty buckets in display order.
 */
export function groupConversations<T extends { last_activity_at: string }>(
  conversations: readonly T[],
  now: Date = new Date(),
): ConversationGroup<T>[] {
  const buckets: ConversationGroup<T>[] = [
    { label: TODAY, items: [] },
    { label: YESTERDAY, items: [] },
    { label: LAST_WEEK, items: [] },
    { label: OLDER, items: [] },
  ];

  for (const conversation of conversations) {
    const offset = dayOffset(conversation.last_activity_at, now);
    const index = offset <= 0 ? 0 : offset === 1 ? 1 : offset < 7 ? 2 : 3;
    buckets[index]?.items.push(conversation);
  }

  for (const bucket of buckets) {
    bucket.items.sort(
      (left, right) =>
        (parseTimestamp(right.last_activity_at)?.getTime() ?? 0) -
        (parseTimestamp(left.last_activity_at)?.getTime() ?? 0),
    );
  }

  return buckets.filter((bucket) => bucket.items.length > 0);
}

/**
 * Filters conversations by a case-insensitive title match.
 *
 * @param conversations Conversations to filter.
 * @param term Search term; blank keeps every row.
 * @returns The matching conversations, order preserved.
 */
export function filterConversations<T extends { title: string }>(
  conversations: readonly T[],
  term: string,
): T[] {
  const needle = term.trim().toLowerCase();
  if (needle === '') {
    return [...conversations];
  }
  return conversations.filter((conversation) => conversation.title.toLowerCase().includes(needle));
}
