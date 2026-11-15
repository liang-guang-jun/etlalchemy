import { useState } from 'react';
import { Send, X } from 'lucide-react';

import type { CommentTarget } from '@/entities/comment';
import { normalizeError } from '@/shared/api/error';
import { Button, Input } from '@/shared/ui';

import { useAddComment, useCreateThread } from '../api/mutation';
import { resolveMentions, useMentionSuggestions, type MentionPick } from '../model/directory';
import { MentionTextarea } from './MentionTextarea';

interface ComposerShellProps {
  placeholder: string;
  submitLabel: string;
  rows: number;
  autoFocus?: boolean;
  /** Whether the optional thread title is offered. */
  withTitle?: boolean;
  pending: boolean;
  error: string | null;
  /** Advisory text returned by the API after a deep reply. */
  warning: string | null;
  onSubmit: (body: string, title: string, mentions: string[]) => void;
  onCancel?: () => void;
}

/**
 * Renders the textarea, the mention hint and the submit row of a comment editor.
 *
 * @param props Component props.
 * @returns The composer element.
 */
function ComposerShell({
  placeholder,
  submitLabel,
  rows,
  autoFocus = false,
  withTitle = false,
  pending,
  error,
  warning,
  onSubmit,
  onCancel,
}: ComposerShellProps) {
  const [body, setBody] = useState('');
  const [title, setTitle] = useState('');
  const [titleOpen, setTitleOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [picks, setPicks] = useState<MentionPick[]>([]);
  const { suggestions } = useMentionSuggestions(query);
  const trimmed = body.trim();
  const canSubmit = trimmed !== '' && !pending;

  const submit = (): void => {
    if (!canSubmit) {
      return;
    }
    onSubmit(trimmed, title.trim(), resolveMentions(trimmed, picks));
    setBody('');
    setTitle('');
    setTitleOpen(false);
    setPicks([]);
    setQuery('');
  };

  return (
    <div className="space-y-2">
      {warning === null ? null : (
        <p
          role="status"
          className="rounded-md border border-warning/40 bg-warning/15 px-3 py-2 text-xs text-warning-ink"
        >
          {warning}
        </p>
      )}
      {withTitle && titleOpen ? (
        <Input
          aria-label="Thread title"
          placeholder="Title (optional)"
          value={title}
          onChange={(event) => {
            setTitle(event.target.value);
          }}
        />
      ) : null}
      <MentionTextarea
        value={body}
        onChange={setBody}
        suggestions={suggestions}
        onQuery={setQuery}
        onPick={(user) => {
          setPicks((current) => [
            ...current.filter((pick) => pick.id !== user.user_id),
            { id: user.user_id, name: user.display_name },
          ]);
        }}
        rows={rows}
        autoFocus={autoFocus}
        placeholder={`${placeholder} (@ to mention, ⌘↵ to send)`}
        invalid={error !== null}
        onSubmit={submit}
      />
      {error === null ? null : <p className="text-xs text-danger">{error}</p>}
      <div className="flex items-center gap-2">
        <div className="ml-auto flex items-center gap-2">
          {withTitle && !titleOpen ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setTitleOpen(true);
              }}
            >
              Add title
            </Button>
          ) : null}
          {onCancel === undefined ? null : (
            <Button size="sm" variant="ghost" onClick={onCancel}>
              <X className="size-3.5" aria-hidden="true" />
              Cancel
            </Button>
          )}
          <Button
            size="sm"
            variant="primary"
            loading={pending}
            disabled={!canSubmit}
            onClick={submit}
          >
            <Send className="size-3.5" aria-hidden="true" />
            {submitLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}

export interface NewThreadComposerProps {
  /** Target the new thread hangs off. */
  target: CommentTarget;
}

/**
 * Starts a discussion on a target.
 *
 * @param props Component props.
 * @returns The new-thread composer.
 */
export function NewThreadComposer({ target }: NewThreadComposerProps) {
  const mutation = useCreateThread();

  return (
    <ComposerShell
      rows={3}
      withTitle
      submitLabel="Start discussion"
      placeholder={`Start a discussion about ${target.label}…`}
      pending={mutation.isPending}
      error={mutation.error === null ? null : normalizeError(mutation.error).detail}
      warning={null}
      onSubmit={(body, title, mentions) => {
        mutation.mutate({
          target_type: target.type,
          target_id: target.id,
          title,
          body,
          mentions,
        });
      }}
    />
  );
}

export interface ReplyComposerProps {
  /** Thread that receives the reply. */
  threadId: string;
  /** Comment being answered, or `null` for a new root comment. */
  parentCommentId: string | null;
  placeholder?: string;
  autoFocus?: boolean;
  onDone?: () => void;
}

/**
 * Answers one comment, or adds another root comment to a thread.
 *
 * A `depth_warning` from the API is shown above the editor, because the reply
 * already exists by then and a new thread is the suggested alternative.
 *
 * @param props Component props.
 * @returns The reply composer.
 */
export function ReplyComposer({
  threadId,
  parentCommentId,
  placeholder = 'Reply…',
  autoFocus = true,
  onDone,
}: ReplyComposerProps) {
  const mutation = useAddComment(threadId);

  return (
    <ComposerShell
      rows={2}
      autoFocus={autoFocus}
      submitLabel="Reply"
      placeholder={placeholder}
      pending={mutation.isPending}
      error={mutation.error === null ? null : normalizeError(mutation.error).detail}
      warning={mutation.data?.depth_warning ?? null}
      onCancel={onDone}
      onSubmit={(body, _title, mentions) => {
        mutation.mutate(
          {
            body,
            parent_comment_id: parentCommentId,
            mentions,
          },
          {
            // A shallow reply closes the editor; a deep one keeps it open so the
            // advisory above it can be read.
            onSuccess: (created) => {
              if (created.depth_warning === null) {
                onDone?.();
              }
            },
          },
        );
      }}
    />
  );
}
