import { useEffect, useRef, useState } from 'react';
import { Check, Copy, Maximize2, Pencil, Sparkles } from 'lucide-react';

import {
  hasRichContent,
  useStepsCollapsed,
  type AgentMessage,
  type AgentToolCall,
  type AgentTranscript,
} from '@/entities/agent';
import { ApprovalCard, useUrnLabels } from '@/features/agent-chat';
import { cn } from '@/shared/lib/cn';
import { formatRelative } from '@/shared/lib/date';
import { keepInView } from '@/shared/lib/scroll';
import { Markdown } from '@/shared/ui/markdown';
import { Badge, Button } from '@/shared/ui';

import { ReasoningBlock } from './ReasoningBlock';
import { StepsCollapse } from './StepsCollapse';
import { ToolCallCard } from './ToolCallCard';
import { ToolCallDrawer } from './ToolCallDrawer';

export interface MessageListProps {
  /** Conversation the transcript belongs to; approvals need it. */
  conversationId: string | null;
  /** Transcript to render. */
  transcript: AgentTranscript;
  /** Compact styling of the floating widget. */
  compact?: boolean;
  /** Called by the "open full screen" hint of a rich answer. */
  onOpenFullScreen?: () => void;
  /** Suggested prompts shown before the first message. */
  suggestions?: string[];
  /** Called when the user picks a suggestion. */
  onSuggestion?: (prompt: string) => void;
  /**
   * Called when the reader saves an edited user message.
   *
   * The surface regenerates the answer; without the callback the list only
   * offers copying, because it never writes the transcript itself.
   */
  onEditMessage?: (messageId: string, content: string) => void;
}

/** How long the copy confirmation stays visible. */
const COPIED_FEEDBACK_MS = 1500;

/**
 * Renders a button that copies one message to the clipboard.
 *
 * @param props Component props.
 * @returns The copy button.
 */
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) {
        window.clearTimeout(timer.current);
      }
    },
    [],
  );

  return (
    <button
      type="button"
      aria-label={copied ? 'Copied' : 'Copy message'}
      title="Copy"
      className="flex size-6 items-center justify-center rounded-sm text-text-disabled transition-colors hover:bg-bg-hover hover:text-text-primary"
      onClick={() => {
        const clipboard = navigator.clipboard;
        if (clipboard === undefined) {
          return;
        }
        void clipboard
          .writeText(text)
          .then(() => {
            setCopied(true);
            if (timer.current !== null) {
              window.clearTimeout(timer.current);
            }
            timer.current = window.setTimeout(() => {
              setCopied(false);
            }, COPIED_FEEDBACK_MS);
          })
          .catch(() => undefined);
      }}
    >
      {copied ? (
        <Check className="size-3.5 text-success" aria-hidden="true" />
      ) : (
        <Copy className="size-3.5" aria-hidden="true" />
      )}
    </button>
  );
}

/**
 * Renders the edit button of a user message.
 *
 * @param props Component props.
 * @returns The edit button.
 */
function EditButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label="Edit message"
      title="Edit and regenerate"
      className="flex size-6 items-center justify-center rounded-sm text-text-disabled transition-colors hover:bg-bg-hover hover:text-text-primary"
      onClick={onClick}
    >
      <Pencil className="size-3.5" aria-hidden="true" />
    </button>
  );
}

/**
 * Describes how much of the transcript is already on screen.
 *
 * It grows with every token, thinking chunk, tool card and approval card, so an
 * effect depending on it follows the answer while it is being written.
 *
 * @param transcript Transcript to measure.
 * @returns A comparable fingerprint of the rendered content.
 */
function progressOf(transcript: AgentTranscript): string {
  const messages = transcript.messages
    .map((message) =>
      [
        message.messageId,
        message.content.length,
        message.reasoning.length,
        message.steps.length,
        message.tools.length,
      ].join(':'),
    )
    .join('|');
  return `${messages}#${String(transcript.approvals.length)}`;
}

/**
 * Renders one assistant message, tightening the typography in the widget.
 *
 * The widget renders the same markdown as the page, so tables, code blocks and
 * the URN links of an answer stay readable instead of collapsing into plain
 * text. A wide block scrolls inside its own box, so the narrow panel never gains
 * a horizontal scrollbar. The links show the name of the object rather than its
 * id, because the answer already talks about `dev` or `test`.
 *
 * @param props Component props.
 * @returns The message content.
 */
function AssistantBody({
  message,
  compact,
  onOpenFullScreen,
}: {
  message: AgentMessage;
  compact: boolean;
  onOpenFullScreen?: (() => void) | undefined;
}) {
  const urnLabels = useUrnLabels(message.content);

  if (!compact) {
    return <Markdown urnLabels={urnLabels}>{message.content}</Markdown>;
  }
  return (
    <div>
      <Markdown className="text-[13px] [&_pre]:text-[11px] [&_table]:text-xs" urnLabels={urnLabels}>
        {message.content}
      </Markdown>
      {!hasRichContent(message.content) || onOpenFullScreen === undefined ? null : (
        <button
          type="button"
          className="mt-1 flex items-center gap-1 text-[11px] text-text-secondary hover:text-text-primary"
          onClick={onOpenFullScreen}
        >
          <Maximize2 className="size-3" aria-hidden="true" />
          Open full screen
        </button>
      )}
    </div>
  );
}

/**
 * Renders one assistant message: its trace, its sources and its answer.
 *
 * The trace stays open while the answer streams and folds once it is complete,
 * so a long tool sequence never pushes the answer off the screen for good; the
 * sources stay visible, because a reader checks them while reading the answer.
 *
 * @param props Component props.
 * @returns The message.
 */
function AssistantMessage({
  message,
  compact,
  onOpenFullScreen,
  onOpenTool,
}: {
  message: AgentMessage;
  compact: boolean;
  onOpenFullScreen?: (() => void) | undefined;
  onOpenTool: (call: AgentToolCall) => void;
}) {
  const { collapsed, toggle } = useStepsCollapsed(message);

  return (
    <article className="min-w-0">
      <div className="mb-1 flex items-center gap-2 text-[11px] text-text-disabled">
        <Sparkles className="size-3" aria-hidden="true" />
        Agent
        <span>{formatRelative(message.createdAt)}</span>
        {message.interrupted ? <Badge tone="warning">interrupted</Badge> : null}
        {message.content === '' ? null : (
          <span className="ml-auto">
            <CopyButton text={message.content} />
          </span>
        )}
      </div>

      {message.steps.length === 0 ? null : (
        <StepsCollapse message={message} collapsed={collapsed} onToggle={toggle} compact={compact}>
          {message.steps.map((step, index) =>
            step.kind === 'reasoning' ? (
              <ReasoningBlock
                key={`reasoning-${String(index)}`}
                text={step.text}
                streaming={
                  message.streaming && message.content === '' && index === message.steps.length - 1
                }
                compact={compact}
              />
            ) : (
              <ToolCallCard
                key={`${step.call.tool}-${step.call.argsHash}-${String(index)}`}
                call={step.call}
                compact={compact}
                onOpen={onOpenTool}
              />
            ),
          )}
        </StepsCollapse>
      )}

      <AssistantBody message={message} compact={compact} onOpenFullScreen={onOpenFullScreen} />
      {message.streaming ? (
        <span
          aria-label="The agent is still writing"
          className="mt-1 inline-block h-4 w-1.5 animate-pulse bg-text-secondary align-middle"
        />
      ) : null}
    </article>
  );
}

/**
 * Renders the transcript of a conversation with its traces and approvals.
 *
 * User messages are right-aligned bubbles; agent answers use the full width so
 * tables and code have room, matching the reading mode of the full page.
 *
 * @param props Component props.
 * @returns The transcript region.
 */
export function MessageList({
  conversationId,
  transcript,
  compact = false,
  onOpenFullScreen,
  suggestions = [],
  onSuggestion,
  onEditMessage,
}: MessageListProps) {
  const { messages, run, approvals } = transcript;
  const [selectedTool, setSelectedTool] = useState<AgentToolCall | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);
  const progress = progressOf(transcript);
  const firstMessageId = messages[0]?.messageId ?? '';
  const streaming = run.status === 'streaming';
  const running = streaming || run.status === 'awaiting_approval';

  const startEdit = (message: AgentMessage) => {
    setEditingId(message.messageId);
    setDraft(message.content);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setDraft('');
  };

  const saveEdit = () => {
    const content = draft.trim();
    if (editingId === null || content === '' || onEditMessage === undefined) {
      return;
    }
    const messageId = editingId;
    cancelEdit();
    onEditMessage(messageId, content);
  };

  // Follow the stream: the answer grows downwards, so the newest text has to be
  // inside the viewport while it is written. A conversation that just opened
  // jumps to its end once, whatever the reader did in the previous one.
  useEffect(() => {
    keepInView(bottomRef.current, streaming, false);
  }, [progress, streaming]);

  useEffect(() => {
    keepInView(bottomRef.current, streaming, true);
  }, [firstMessageId, conversationId, streaming]);

  if (messages.length === 0 && run.status !== 'streaming' && approvals.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
        <span className="flex size-10 items-center justify-center rounded-full bg-brand/15">
          <Sparkles className="size-5 text-brand-ink" aria-hidden="true" />
        </span>
        <div>
          <p className="text-sm font-medium text-text-primary">Ask about your metadata</p>
          <p className="mt-1 text-xs text-text-secondary">
            The agent reads the catalog, semantic models and terms through MCP tools.
          </p>
        </div>
        {suggestions.length === 0 ? null : (
          <div className="flex w-full max-w-sm flex-col gap-1.5">
            {suggestions.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                className="rounded-md border border-border-base bg-bg-surface px-3 py-2 text-left text-xs text-text-secondary transition-colors hover:border-brand hover:text-text-primary"
                onClick={() => {
                  onSuggestion?.(suggestion);
                }}
              >
                {suggestion}
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={cn('flex flex-col', compact ? 'gap-3 p-2' : 'gap-5 p-6')}>
      {messages.map((message) =>
        message.role === 'user' ? (
          <div key={message.messageId} className="flex flex-col items-end gap-1">
            {editingId === message.messageId ? (
              <div
                className={cn(
                  'w-full max-w-[85%] rounded-lg border border-border-base bg-bg-surface p-2',
                  compact && 'max-w-full',
                )}
              >
                <textarea
                  aria-label="Edit message"
                  autoFocus
                  rows={3}
                  value={draft}
                  className="w-full resize-none bg-transparent text-sm text-text-primary outline-none"
                  onChange={(event) => {
                    setDraft(event.target.value);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                      event.preventDefault();
                      saveEdit();
                    }
                    if (event.key === 'Escape') {
                      event.preventDefault();
                      cancelEdit();
                    }
                  }}
                />
                <div className="mt-1 flex justify-end gap-1">
                  <Button size="sm" variant="ghost" onClick={cancelEdit}>
                    Cancel
                  </Button>
                  <Button size="sm" disabled={draft.trim() === ''} onClick={saveEdit}>
                    Save and regenerate
                  </Button>
                </div>
              </div>
            ) : (
              <div
                className={cn(
                  'max-w-[85%] rounded-lg rounded-br-sm bg-brand/20 px-3 py-2 text-sm whitespace-pre-wrap text-text-primary',
                  compact && 'max-w-full',
                )}
              >
                {message.content}
              </div>
            )}
            <div className="flex items-center gap-0.5">
              <CopyButton text={message.content} />
              {onEditMessage === undefined || running || editingId !== null ? null : (
                <EditButton
                  onClick={() => {
                    startEdit(message);
                  }}
                />
              )}
            </div>
          </div>
        ) : (
          <AssistantMessage
            key={message.messageId}
            message={message}
            compact={compact}
            onOpenFullScreen={onOpenFullScreen}
            onOpenTool={setSelectedTool}
          />
        ),
      )}

      {run.status === 'streaming' && messages.every((message) => message.role === 'user') ? (
        <p className="flex items-center gap-2 text-xs text-text-secondary">
          <span className="size-1.5 animate-pulse rounded-full bg-brand" aria-hidden="true" />
          Thinking…
        </p>
      ) : null}

      {run.status === 'failed' && run.error !== null ? (
        <p
          role="alert"
          className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger"
        >
          {run.error}
        </p>
      ) : null}

      {run.status === 'interrupted' ? (
        <p className="text-xs text-text-secondary">
          Generation stopped. The partial answer is kept.
        </p>
      ) : null}

      {conversationId === null || run.status !== 'awaiting_approval'
        ? null
        : approvals
            .filter((approval) => approval.status === 'pending')
            .map((approval) => (
              <ApprovalCard
                key={approval.approvalId}
                conversationId={conversationId}
                approval={approval}
                compact={compact}
              />
            ))}

      <ToolCallDrawer
        call={selectedTool}
        onClose={() => {
          setSelectedTool(null);
        }}
      />

      <div ref={bottomRef} aria-hidden="true" />
    </div>
  );
}
