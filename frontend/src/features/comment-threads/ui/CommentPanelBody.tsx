import { useEffect, useMemo, useState } from 'react';
import { MessagesSquare } from 'lucide-react';

import {
  TARGET_NOUNS,
  targetHref,
  useTarget,
  useThreadDetails,
  useThreads,
  type CommentTarget,
  type Thread,
} from '@/entities/comment';
import { Link } from 'react-router';
import { EmptyState, ErrorState, SearchInput, Skeleton, Tabs } from '@/shared/ui';

import { useAuthorNames } from '../model/directory';
import { useCommentPanelStore } from '../model/store';
import { NewThreadComposer } from './CommentComposer';
import { CommentThreadCard } from './CommentThreadCard';

/** Statuses the panel can show. */
type ThreadStatus = 'OPEN' | 'RESOLVED';

export interface CommentPanelBodyProps {
  /** Target whose threads are listed. */
  target: CommentTarget;
}

/**
 * Renders the discussion of one target.
 *
 * The list and the "start a discussion" editor share the panel: the editor is
 * pinned to the bottom, the threads scroll above it. Comment bodies are loaded
 * per expanded thread, so the list stays a single request.
 *
 * @param props Component props.
 * @returns The discussion panel body.
 */
export function CommentPanelBody({ target }: CommentPanelBodyProps) {
  const focusThreadId = useCommentPanelStore((state) => state.focusThreadId);
  const [status, setStatus] = useState<ThreadStatus>('OPEN');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  // Entry points already know the name and the link; the inbox does not, so the
  // target is described on demand and the header becomes a link either way.
  const unknown = target.href === undefined;
  const described = useTarget(unknown ? target.type : '', unknown ? target.id : '');
  const href =
    target.href ?? (described.data === undefined ? undefined : targetHref(described.data));
  const label = unknown && described.data !== undefined ? described.data.name : target.label;

  // Jumping in from the inbox opens the thread it links to.
  useEffect(() => {
    if (focusThreadId === null) {
      return;
    }
    setStatus('OPEN');
    setExpanded(focusThreadId);
  }, [focusThreadId, target.id]);

  const open = useThreads({ targetType: target.type, targetId: target.id, status: 'OPEN' });
  const resolved = useThreads({
    targetType: target.type,
    targetId: target.id,
    status: 'RESOLVED',
  });

  const rows = useMemo<Thread[]>(
    () => (status === 'OPEN' ? open.data : resolved.data) ?? [],
    [status, open.data, resolved.data],
  );
  const pending = status === 'OPEN' ? open.isPending : resolved.isPending;
  const failed = status === 'OPEN' ? open.isError : resolved.isError;

  // Filtering by a comment body needs the comments; the panel only asks for them
  // while a term is typed, which keeps the idle list to a single request.
  const needle = search.trim().toLowerCase();
  const threads = useThreadDetails(
    rows.map((thread) => thread.thread_id),
    needle !== '',
  );
  const authors = useAuthorNames(
    useMemo(
      () =>
        rows.flatMap((thread, index) => [
          thread.author_user_id,
          ...(threads[index]?.comments ?? []).map((comment) => comment.author_user_id),
        ]),
      [rows, threads],
    ),
  );
  const visible = useMemo(() => {
    if (needle === '') {
      return rows;
    }
    return rows.filter((thread, index) => {
      const comments = threads[index]?.comments ?? [];
      const haystack = [
        thread.title,
        authors.get(thread.author_user_id) ?? '',
        ...comments.flatMap((comment) => [comment.body, authors.get(comment.author_user_id) ?? '']),
      ]
        .join(' ')
        .toLowerCase();
      return haystack.includes(needle);
    });
  }, [rows, threads, authors, needle]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <p className="mb-2 flex min-w-0 items-baseline gap-2 text-[11px] font-semibold tracking-wider text-text-disabled uppercase">
        <span className="shrink-0">{TARGET_NOUNS[target.type]}</span>
        {href === undefined ? (
          <span className="truncate normal-case tracking-normal text-text-secondary">{label}</span>
        ) : (
          <Link
            to={href}
            title={`Open ${label}`}
            className="truncate normal-case tracking-normal text-text-secondary hover:text-text-primary hover:underline"
          >
            {label}
          </Link>
        )}
      </p>

      <Tabs
        className="shrink-0"
        value={status}
        onChange={(value) => {
          setStatus(value === 'RESOLVED' ? 'RESOLVED' : 'OPEN');
        }}
        items={[
          { value: 'OPEN', label: 'Open', count: (open.data ?? []).length },
          { value: 'RESOLVED', label: 'Resolved', count: (resolved.data ?? []).length },
        ]}
      />

      <div className="mt-2 shrink-0">
        <SearchInput
          ariaLabel="Search this discussion"
          placeholder="Search title, comment or author…"
          value={search}
          onChange={setSearch}
        />
      </div>

      <div className="min-h-40 flex-1 space-y-2 overflow-y-auto py-3">
        {pending ? <Skeleton lines={4} /> : null}
        {failed ? (
          <ErrorState
            detail="Failed to load the discussions."
            onRetry={() => {
              void (status === 'OPEN' ? open.refetch() : resolved.refetch());
            }}
          />
        ) : null}
        {!pending && !failed && visible.length === 0 ? (
          <EmptyState
            plain
            icon={<MessagesSquare className="size-6" aria-hidden="true" />}
            title={
              needle === ''
                ? status === 'OPEN'
                  ? 'No discussion yet'
                  : 'Nothing resolved yet'
                : 'Nothing matches'
            }
            description={
              needle !== ''
                ? 'Try another keyword.'
                : status === 'OPEN'
                  ? 'Start the first topic about this object below.'
                  : 'Resolved discussions are kept here.'
            }
          />
        ) : null}
        {visible.map((thread) => (
          <CommentThreadCard
            key={thread.thread_id}
            thread={thread}
            expanded={expanded === thread.thread_id}
            onToggle={() => {
              setExpanded((current) => (current === thread.thread_id ? null : thread.thread_id));
            }}
          />
        ))}
      </div>

      <div className="shrink-0 border-t border-border-base pt-3">
        <NewThreadComposer target={target} />
      </div>
    </div>
  );
}
