import { useMemo, useState } from 'react';
import { MessagesSquare } from 'lucide-react';

import {
  describedTarget,
  TARGET_NOUNS,
  useTargets,
  useThreads,
  type CommentTarget,
  type TargetDescription,
} from '@/entities/comment';
import { useSessionStore } from '@/entities/session';
import { formatRelative } from '@/shared/lib/date';
import { cn } from '@/shared/lib/cn';
import { Badge, EmptyState, ErrorState, SearchInput, Select, Skeleton } from '@/shared/ui';

import { useCommentPanelStore } from '../model/store';

/** Which threads the inbox shows. */
type InboxFilter = 'all' | 'mine' | 'mentions';

const FILTERS = [
  { value: 'all', label: 'All open discussions' },
  { value: 'mine', label: 'Started by me' },
  { value: 'mentions', label: 'Mentioning me' },
];

export interface CommentInboxProps {
  /** Called after a thread is opened, e.g. to close the drawer. */
  onOpened?: () => void;
}

/**
 * Renders the global list of open discussions.
 *
 * The rows are the same threads the contextual panel shows, filtered by who
 * started them or who was mentioned. The object behind each thread is resolved
 * in one batch request, so a row can show its name and link to it instead of a
 * bare id, and the keyword box filters the visible rows on that name, the thread
 * title and the target type.
 *
 * @param props Component props.
 * @returns The inbox body.
 */
export function CommentInbox({ onOpened }: CommentInboxProps) {
  const currentUserId = useSessionStore((state) => state.userId) ?? '';
  const openPanel = useCommentPanelStore((state) => state.openPanel);
  const [filter, setFilter] = useState<InboxFilter>('all');
  const [term, setTerm] = useState('');

  const query = useMemo(
    () => ({
      status: 'OPEN',
      ...(filter === 'mine' ? { authorUserId: currentUserId } : {}),
      ...(filter === 'mentions' ? { mentionUserId: currentUserId } : {}),
    }),
    [filter, currentUserId],
  );
  const threads = useThreads(query, currentUserId !== '');
  const rows = useMemo(() => threads.data ?? [], [threads.data]);

  const refs = useMemo(
    () =>
      rows.map((thread) => ({
        targetType: thread.target_type,
        targetId: thread.target_id,
      })),
    [rows],
  );
  const targets = useTargets(refs);
  const described = useMemo(() => {
    const byKey = new Map<string, TargetDescription>();
    for (const description of targets.data ?? []) {
      byKey.set(`${description.target_type}:${description.target_id}`, description);
    }
    return byKey;
  }, [targets.data]);

  const targetOf = (targetType: string, targetId: string): CommentTarget => {
    const description = described.get(`${targetType}:${targetId}`);
    if (description !== undefined) {
      return describedTarget(description);
    }
    return {
      type: targetType in TARGET_NOUNS ? (targetType as CommentTarget['type']) : 'catalog',
      id: targetId,
      label: targetId.slice(0, 8),
    };
  };

  const needle = term.trim().toLowerCase();
  const visible = useMemo(
    () =>
      needle === ''
        ? rows
        : rows.filter((thread) => {
            const description = described.get(`${thread.target_type}:${thread.target_id}`);
            const haystack = [
              thread.title,
              description?.path ?? '',
              TARGET_NOUNS[thread.target_type as CommentTarget['type']] ?? thread.target_type,
            ]
              .join(' ')
              .toLowerCase();
            return haystack.includes(needle);
          }),
    [rows, needle, described],
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select
          aria-label="Filter discussions"
          value={filter}
          options={FILTERS}
          className="h-8 w-auto flex-1"
          onChange={(event) => {
            const value = event.target.value;
            setFilter(value === 'mine' ? 'mine' : value === 'mentions' ? 'mentions' : 'all');
          }}
        />
        <SearchInput
          ariaLabel="Search discussions"
          placeholder="Search discussions…"
          value={term}
          onChange={setTerm}
        />
      </div>

      {threads.isPending ? <Skeleton lines={5} /> : null}
      {threads.isError ? (
        <ErrorState
          detail="Failed to load the discussions."
          onRetry={() => {
            void threads.refetch();
          }}
        />
      ) : null}

      {!threads.isPending && !threads.isError && visible.length === 0 ? (
        <EmptyState
          plain
          icon={<MessagesSquare className="size-6" aria-hidden="true" />}
          title={needle === '' ? 'No open discussion' : 'Nothing matches'}
          description={
            needle !== ''
              ? 'Try another keyword.'
              : filter === 'all'
                ? 'Threads appear here once someone starts one.'
                : 'Nothing matches this filter right now.'
          }
        />
      ) : null}

      <ul className="space-y-1">
        {visible.map((thread) => {
          const target = targetOf(thread.target_type, thread.target_id);
          const description = described.get(`${thread.target_type}:${thread.target_id}`);
          return (
            <li key={thread.thread_id}>
              <button
                type="button"
                onClick={() => {
                  openPanel(target, thread.thread_id);
                  onOpened?.();
                }}
                className={cn(
                  'flex w-full flex-col gap-1 rounded-md border border-border-base px-3 py-2 text-left transition-colors',
                  'hover:border-border-strong hover:bg-bg-hover-subtle',
                )}
              >
                <span className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium text-text-primary">
                    {thread.title === '' ? 'Discussion' : thread.title}
                  </span>
                  <Badge tone="info" className="ml-auto shrink-0">
                    {TARGET_NOUNS[target.type]}
                  </Badge>
                </span>
                <span className="flex items-center gap-1.5 text-[11px] text-text-secondary">
                  <span className="truncate">{description?.path ?? target.label}</span>
                  <span>·</span>
                  <span className="shrink-0">{formatRelative(thread.last_activity_at)}</span>
                  <span>·</span>
                  <span className="shrink-0">
                    {thread.comment_count} {thread.comment_count === 1 ? 'comment' : 'comments'}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
