import { useState } from 'react';
import { Check, ChevronRight, CornerDownRight, RotateCcw, Trash2 } from 'lucide-react';

import {
  buildCommentTree,
  indentFor,
  useThread,
  type CommentNode,
  type Thread,
} from '@/entities/comment';
import { selectIsSystemAdmin, useSessionStore } from '@/entities/session';
import { formatRelative } from '@/shared/lib/date';
import { cn } from '@/shared/lib/cn';
import { Badge, Button, ConfirmDialog, Skeleton } from '@/shared/ui';

import {
  useDiscardComment,
  useDiscardThread,
  useReopenThread,
  useResolveThread,
} from '../api/mutation';
import { useAuthorName } from '../model/directory';
import { ReplyComposer } from './CommentComposer';

/** What the card is about to delete, if anything. */
type PendingDelete = { kind: 'thread' } | { kind: 'comment'; commentId: string } | null;

interface CommentItemProps {
  node: CommentNode;
  threadId: string;
  canManage: (authorId: string) => boolean;
  replyingTo: string | null;
  onReply: (commentId: string | null) => void;
  onDelete: (commentId: string) => void;
}

/**
 * Renders one comment with its replies.
 *
 * @param props Component props.
 * @returns The comment block.
 */
function CommentItem({
  node,
  threadId,
  canManage,
  replyingTo,
  onReply,
  onDelete,
}: CommentItemProps) {
  const { comment, children } = node;
  const author = useAuthorName(comment.author_user_id);
  const indented = indentFor(comment.depth) * 12;

  return (
    <div style={{ marginLeft: indented }} className="space-y-1">
      <div className="rounded-md px-2 py-1.5 transition-colors hover:bg-bg-hover-subtle">
        <div className="flex items-center gap-2 text-[11px] text-text-secondary">
          <span className="font-medium text-text-primary">{author}</span>
          <span>{formatRelative(comment.created_at)}</span>
          {comment.edited_at === null ? null : <span>· edited</span>}
          <div className="ml-auto flex items-center gap-1">
            <button
              type="button"
              onClick={() => {
                onReply(comment.comment_id);
              }}
              className="flex items-center gap-1 rounded-sm px-1 text-[11px] text-text-secondary transition-colors hover:text-text-primary"
            >
              <CornerDownRight className="size-3" aria-hidden="true" />
              Reply
            </button>
            {canManage(comment.author_user_id) ? (
              <button
                type="button"
                aria-label="Delete comment"
                onClick={() => {
                  onDelete(comment.comment_id);
                }}
                className="rounded-sm p-0.5 text-text-disabled transition-colors hover:text-danger"
              >
                <Trash2 className="size-3" aria-hidden="true" />
              </button>
            ) : null}
          </div>
        </div>
        <p className="whitespace-pre-wrap text-sm text-text-primary">{comment.body}</p>
      </div>

      {replyingTo === comment.comment_id ? (
        <ReplyComposer
          threadId={threadId}
          parentCommentId={comment.comment_id}
          onDone={() => {
            onReply(null);
          }}
        />
      ) : null}

      {children.map((child) => (
        <CommentItem
          key={child.comment.comment_id}
          node={child}
          threadId={threadId}
          canManage={canManage}
          replyingTo={replyingTo}
          onReply={onReply}
          onDelete={onDelete}
        />
      ))}
    </div>
  );
}

export interface CommentThreadCardProps {
  thread: Thread;
  expanded: boolean;
  onToggle: () => void;
}

/**
 * Renders one discussion: its header, and while expanded its comment tree.
 *
 * The comment bodies are only fetched for the expanded card, so a long list of
 * threads costs one request per opened thread instead of one per row.
 *
 * @param props Component props.
 * @returns The thread card.
 */
export function CommentThreadCard({ thread, expanded, onToggle }: CommentThreadCardProps) {
  const author = useAuthorName(thread.author_user_id);
  const currentUserId = useSessionStore((state) => state.userId) ?? '';
  const isAdmin = useSessionStore(selectIsSystemAdmin);
  const detail = useThread(expanded ? thread.thread_id : '');
  const resolve = useResolveThread();
  const reopen = useReopenThread();
  const discardThread = useDiscardThread();
  const discardComment = useDiscardComment(thread.thread_id);
  const [replyingTo, setReplyingTo] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<PendingDelete>(null);

  const canManage = (authorId: string): boolean => isAdmin || authorId === currentUserId;
  const managed = canManage(thread.author_user_id);
  const comments = detail.data?.comments ?? [];
  const roots = buildCommentTree(comments);
  const open = thread.status === 'OPEN';

  return (
    <article
      className={cn(
        'rounded-md border border-border-base bg-bg-surface transition-colors',
        expanded && 'shadow-sm',
      )}
    >
      <div className="flex items-start gap-2 px-3 py-2">
        <button
          type="button"
          aria-expanded={expanded}
          onClick={onToggle}
          className="flex min-w-0 flex-1 items-start gap-2 text-left"
        >
          <ChevronRight
            className={cn(
              'mt-0.5 size-3.5 shrink-0 text-text-secondary transition-transform',
              expanded && 'rotate-90',
            )}
            aria-hidden="true"
          />
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-2">
              <span className="truncate text-sm font-medium text-text-primary">
                {thread.title === '' ? 'Discussion' : thread.title}
              </span>
              <Badge tone={open ? 'info' : 'success'}>{thread.status}</Badge>
            </span>
            <span className="mt-0.5 flex items-center gap-1.5 text-[11px] text-text-secondary">
              <span className="truncate">{author}</span>
              <span>·</span>
              <span className="shrink-0">{formatRelative(thread.last_activity_at)}</span>
              <span>·</span>
              <span className="shrink-0">
                {thread.comment_count} {thread.comment_count === 1 ? 'comment' : 'comments'}
              </span>
            </span>
          </span>
        </button>

        {/* The status actions live in the header so the reading flow below stays
            uninterrupted; only the transition that applies to the status shows. */}
        <span className="flex shrink-0 items-center gap-1">
          {open ? (
            <Button
              size="sm"
              variant="ghost"
              loading={resolve.isPending}
              onClick={() => {
                resolve.mutate(thread.thread_id);
              }}
            >
              <Check className="size-3.5" aria-hidden="true" />
              Resolve
            </Button>
          ) : (
            <Button
              size="sm"
              variant="ghost"
              loading={reopen.isPending}
              onClick={() => {
                reopen.mutate(thread.thread_id);
              }}
            >
              <RotateCcw className="size-3.5" aria-hidden="true" />
              Reopen
            </Button>
          )}
          {managed ? (
            <button
              type="button"
              aria-label="Delete discussion"
              title="Delete discussion"
              onClick={() => {
                setPendingDelete({ kind: 'thread' });
              }}
              className="flex size-7 items-center justify-center rounded-sm text-text-disabled transition-colors hover:bg-danger/10 hover:text-danger"
            >
              <Trash2 className="size-3.5" aria-hidden="true" />
            </button>
          ) : null}
        </span>
      </div>

      {expanded ? (
        <div className="space-y-2 border-t border-border-base px-3 py-2">
          {detail.isPending ? <Skeleton lines={3} /> : null}
          {detail.isError ? (
            <p className="text-xs text-danger">Failed to load the comments.</p>
          ) : null}
          {!detail.isPending && roots.length === 0 ? (
            <p className="text-xs text-text-secondary">No comment yet.</p>
          ) : null}

          {roots.map((node) => (
            <CommentItem
              key={node.comment.comment_id}
              node={node}
              threadId={thread.thread_id}
              canManage={canManage}
              replyingTo={replyingTo}
              onReply={setReplyingTo}
              onDelete={(commentId) => {
                setPendingDelete({ kind: 'comment', commentId });
              }}
            />
          ))}

          {replyingTo === null ? (
            <button
              type="button"
              onClick={() => {
                setReplyingTo('');
              }}
              className="text-xs text-text-secondary transition-colors hover:text-text-primary"
            >
              New Comment
            </button>
          ) : null}
          {replyingTo === '' ? (
            <ReplyComposer
              threadId={thread.thread_id}
              parentCommentId={null}
              placeholder="Add a comment to this discussion…"
              onDone={() => {
                setReplyingTo(null);
              }}
            />
          ) : null}
        </div>
      ) : null}

      <ConfirmDialog
        open={pendingDelete !== null}
        danger
        title={pendingDelete?.kind === 'thread' ? 'Delete discussion' : 'Delete comment'}
        description={
          pendingDelete?.kind === 'thread'
            ? 'Deletes the discussion with all its comments.'
            : 'Deletes this comment; its replies stay.'
        }
        confirmLabel="Delete"
        loading={discardThread.isPending || discardComment.isPending}
        onCancel={() => {
          setPendingDelete(null);
        }}
        onConfirm={() => {
          if (pendingDelete === null) {
            return;
          }
          if (pendingDelete.kind === 'thread') {
            discardThread.mutate(thread.thread_id, {
              onSuccess: () => {
                setPendingDelete(null);
              },
            });
            return;
          }
          discardComment.mutate(pendingDelete.commentId, {
            onSuccess: () => {
              setPendingDelete(null);
            },
          });
        }}
      />
    </article>
  );
}
