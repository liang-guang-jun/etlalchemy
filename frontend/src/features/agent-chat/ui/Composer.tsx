import { useEffect, useRef, useState } from 'react';
import { ArrowUp, Square } from 'lucide-react';

import { useRunStatus } from '@/entities/agent';
import { cn } from '@/shared/lib/cn';
import { Button, Textarea } from '@/shared/ui';

import { useAgentChat } from '../model/use-agent-chat';

export interface ComposerProps {
  /** Conversation the prompt goes to, or `null` to start one. */
  conversationId: string | null;
  /** Called with the id of a conversation the prompt created. */
  onConversationCreated?: (conversationId: string) => void;
  /** Chips shown above the input, e.g. the page the user is on. */
  contextLabels?: string[];
  /**
   * Page context forwarded with every prompt, `null` when there is none.
   *
   * The floating widget sends the page it currently shows; the server turns it
   * into instructions, so the transcript stays free of injected text.
   */
  contextNote?: string | null;
  /** Compact styling of the floating widget. */
  compact?: boolean;
  /** Focuses the input when the surface opens. */
  autoFocus?: boolean;
}

/**
 * Renders the prompt input with its send and stop controls.
 *
 * Enter sends and Shift+Enter inserts a line break, matching every other chat
 * composer users are used to.
 *
 * @param props Component props.
 * @returns The composer element.
 */
export function Composer({
  conversationId,
  onConversationCreated,
  contextLabels = [],
  contextNote = null,
  compact = false,
  autoFocus = false,
}: ComposerProps) {
  const [value, setValue] = useState('');
  const { send, stop, running, error } = useAgentChat(conversationId, {
    ...(onConversationCreated === undefined ? {} : { onConversationCreated }),
  });
  const status = useRunStatus(conversationId);
  // A paused run blocks new messages, so the composer must say so instead of
  // pretending the agent is still writing.
  const awaitingApproval = status === 'awaiting_approval';
  const streaming = status === 'streaming';
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (autoFocus) {
      textareaRef.current?.focus();
    }
  }, [autoFocus]);

  const submit = () => {
    if (running) {
      return;
    }
    const prompt = value.trim();
    if (prompt === '') {
      return;
    }
    setValue('');
    void send(prompt, { pageContext: contextNote });
  };

  return (
    <div className={cn('shrink-0', compact ? 'p-2' : 'border-t border-border-base p-3')}>
      {contextLabels.length > 0 ? (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {contextLabels.map((label) => (
            <span
              key={label}
              className="inline-flex max-w-full items-center gap-1 rounded-full border border-border-base bg-bg-canvas px-2 py-0.5 text-[11px] text-text-secondary"
            >
              <span className="size-1.5 rounded-full bg-brand" aria-hidden="true" />
              <span className="truncate">{label}</span>
            </span>
          ))}
        </div>
      ) : null}

      <div
        className={cn(
          'flex items-end gap-2 rounded-lg border border-border-strong bg-bg-surface p-2',
          'focus-within:border-brand focus-within:ring-2 focus-within:ring-brand/30',
        )}
      >
        <Textarea
          ref={textareaRef}
          rows={compact ? 2 : 3}
          value={value}
          aria-label="Message the agent"
          placeholder={
            awaitingApproval
              ? 'Waiting for your approval…'
              : streaming
                ? 'The agent is working…'
                : 'Ask about your data…'
          }
          className="max-h-40 resize-none border-0 bg-transparent p-1 focus:ring-0"
          onChange={(event) => {
            setValue(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
        />
        {streaming ? (
          <Button
            variant="secondary"
            size="sm"
            aria-label="Stop generation"
            title="Stop generation"
            icon={<Square className="size-3.5 fill-current" />}
            onClick={stop}
          >
            <span className="sr-only">Stop</span>
          </Button>
        ) : (
          <Button
            size="sm"
            aria-label="Send message"
            title={awaitingApproval ? 'A run is waiting for your decision' : 'Send message'}
            disabled={value.trim() === '' || running}
            icon={<ArrowUp className="size-4" />}
            onClick={submit}
          >
            <span className="sr-only">Send</span>
          </Button>
        )}
      </div>

      {error === null ? null : (
        <p role="alert" className="mt-1.5 text-xs text-danger">
          {error}
        </p>
      )}

      {compact ? null : (
        <p className="mt-1.5 text-[11px] text-text-disabled">
          Enter sends · Shift+Enter inserts a line break
        </p>
      )}
    </div>
  );
}
