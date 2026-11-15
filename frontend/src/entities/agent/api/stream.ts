import { apiUrl, readAccessToken } from '@/shared/api/client';
import { openEventStream } from '@/shared/api/sse';

import { parseAgentEvent, type AgentEvent } from '../model/events';

/**
 * Decodes one SSE frame into an agent event.
 *
 * @param frame Event name and JSON payload of the frame.
 * @returns The decoded event, or `null` for a frame this client does not know.
 */
function decode(frame: { event: string; data: string }): AgentEvent | null {
  return parseAgentEvent(frame.event, frame.data);
}

/** Options shared by the two streaming endpoints. */
export interface StreamOptions {
  /** Cancels the run; the caller shows the answer as interrupted. */
  signal?: AbortSignal;
  /** Receives every decoded event, in order. */
  onEvent: (event: AgentEvent) => void;
}

/** Options of {@link streamAgentMessage}. */
export interface StreamMessageOptions extends StreamOptions {
  /** Conversation the message belongs to. */
  conversationId: string;
  /** Prompt typed by the user. */
  content: string;
  /** Provider override; the conversation default is used when omitted. */
  llmProviderId?: string | null;
  /** Whether destructive tools of this run run without asking for a decision. */
  autoApprove?: boolean;
  /**
   * Page the reader has open, spliced into the system prompt by the server.
   *
   * It is a request field, not part of the message: the transcript keeps the
   * typed text only.
   */
  pageContext?: string | null;
}

/** Options of {@link streamApprovalDecision}. */
export interface StreamApprovalOptions extends StreamOptions {
  /** Run that waits for the decision. */
  runId: string;
  /** Approval the decision answers. */
  approvalId: string;
  /** Whether the tool may run. */
  approved: boolean;
}

/** Options of {@link streamEditedMessage}. */
export interface StreamEditedMessageOptions extends StreamOptions {
  /** Conversation the edited message belongs to. */
  conversationId: string;
  /** User message that is rewritten. */
  messageId: string;
  /** New body of the message. */
  content: string;
  /** Whether destructive tools of this run run without asking for a decision. */
  autoApprove?: boolean;
  /** Page the reader has open, spliced into the system prompt by the server. */
  pageContext?: string | null;
}

/**
 * Sends a prompt and feeds the run's events to a callback.
 *
 * The promise settles when the server closes the stream: on `done`, on the
 * pause for an approval, or when the caller aborted.
 *
 * @param options Conversation, prompt, cancellation and the event callback.
 */
export async function streamAgentMessage(options: StreamMessageOptions): Promise<void> {
  await openEventStream(apiUrl(`/agent/conversations/${options.conversationId}/messages:stream`), {
    body: {
      content: options.content,
      llm_provider_id: options.llmProviderId ?? null,
      auto_approve: options.autoApprove ?? false,
      page_context: options.pageContext ?? null,
    },
    token: readAccessToken(),
    requestId: crypto.randomUUID(),
    signal: options.signal,
    onFrame: (frame) => {
      const event = decode(frame);
      if (event !== null) {
        options.onEvent(event);
      }
    },
  });
}

/**
 * Rewrites a user message, drops its successors and streams the regenerated run.
 *
 * The server performs the edit and the truncation in one unit of work before the
 * run starts, so the new answer never sees the old transcript tail.
 *
 * @param options Conversation, message, new body, cancellation and the callback.
 */
export async function streamEditedMessage(options: StreamEditedMessageOptions): Promise<void> {
  await openEventStream(
    apiUrl(
      `/agent/conversations/${options.conversationId}/messages/${options.messageId}/edit:stream`,
    ),
    {
      body: {
        content: options.content,
        auto_approve: options.autoApprove ?? false,
        page_context: options.pageContext ?? null,
      },
      token: readAccessToken(),
      requestId: crypto.randomUUID(),
      signal: options.signal,
      onFrame: (frame) => {
        const event = decode(frame);
        if (event !== null) {
          options.onEvent(event);
        }
      },
    },
  );
}

/**
 * Records an approval decision and streams the rest of the paused run.
 *
 * @param options Run, approval, decision, cancellation and the event callback.
 */
export async function streamApprovalDecision(options: StreamApprovalOptions): Promise<void> {
  await openEventStream(
    apiUrl(`/agent/runs/${options.runId}/approvals/${options.approvalId}:stream`),
    {
      body: { approved: options.approved },
      token: readAccessToken(),
      requestId: crypto.randomUUID(),
      signal: options.signal,
      onFrame: (frame) => {
        const event = decode(frame);
        if (event !== null) {
          options.onEvent(event);
        }
      },
    },
  );
}
