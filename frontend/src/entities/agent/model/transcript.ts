import type { AgentEvent } from './events';

/** Lifecycle of one streamed answer shown in the UI. */
export type AgentRunStatus =
  'idle' | 'streaming' | 'awaiting_approval' | 'completed' | 'failed' | 'interrupted';

/** One MCP tool call of an assistant message. */
export interface AgentToolCall {
  /** Name of the tool. */
  tool: string;
  /** Digest of the arguments, kept for provenance. */
  argsHash: string;
  /** `running` until the call returns, then `ok`, `error` or `denied`. */
  status: 'running' | 'ok' | 'error' | 'denied';
  /** Wall-clock duration in milliseconds, once known. */
  durationMs: number | null;
  /** Bracketed error category, when the call failed. */
  errorCode: string | null;
  /** Redacted, truncated JSON of the arguments. */
  argsJson: string;
  /** Truncated text the tool returned. */
  resultPreview: string;
}

/** One MCP resource the agent read. */
export interface AgentResourceRef {
  /** URI of the resource. */
  uri: string;
  /** Payload size in bytes. */
  sizeBytes: number;
  /** MIME type of the payload. */
  mimeType: string;
}

/** One step of the trace, in arrival order. */
export type AgentStep =
  | {
      kind: 'reasoning';
      /** Thinking as it arrived in this segment (a run of deltas). */
      text: string;
    }
  | {
      kind: 'tool';
      /** The same object the message holds in `tools`. */
      call: AgentToolCall;
    };

/** One human-in-the-loop decision. */
export interface AgentApproval {
  /** Id used by the decision endpoint. */
  approvalId: string;
  /** Run that asked for the decision. */
  runId: string | null;
  /** Tool waiting for the decision. */
  tool: string;
  /** Digest of the arguments the tool would receive. */
  argsHash: string;
  /** Why the policy stopped the call. */
  reason: string;
  /** State of the decision. */
  status: 'pending' | 'approved' | 'denied';
}

/** One message of a conversation, as the chat renders it. */
export interface AgentMessage {
  /** Server message id, or a local id for an optimistic user message. */
  messageId: string;
  /** Author of the message. */
  role: 'user' | 'assistant';
  /** Markdown body. */
  content: string;
  /** Moment the message was written. */
  createdAt: string;
  /** Whether the producing stream was interrupted. */
  interrupted: boolean;
  /** Tool calls made while producing the message. */
  tools: AgentToolCall[];
  /** The trace in arrival order: thinking segments and tool calls interleaved. */
  steps: AgentStep[];
  /** Resources read while producing the message. */
  resources: AgentResourceRef[];
  /** Whether tokens are still arriving. */
  streaming: boolean;
  /** Thinking the model streamed before its answer. */
  reasoning: string;
  /**
   * Whether the thinking and the tool calls are folded away.
   *
   * The reducer leaves it `false` while the run writes, so the trace is
   * readable as it happens, and flips it to `true` when the final answer is
   * complete. The user's own choice lives in the store, not here.
   */
  stepsCollapsed: boolean;
  /** Moment the first event of the message arrived, when the server sent one. */
  streamStartedAt: string | null;
  /** Moment the first answer token arrived, when the answer already started. */
  answerStartedAt: string | null;
  /** Moment the message reached its terminal state. */
  completedAt: string | null;
}

/** Everything the chat renders for one conversation. */
export interface AgentTranscript {
  /** Messages, oldest first. */
  messages: AgentMessage[];
  /** State of the streamed answer. */
  run: {
    /** Run id, once the first event named it. */
    runId: string | null;
    /** Lifecycle status. */
    status: AgentRunStatus;
    /** Failure message of a failed run. */
    error: string | null;
    /**
     * Assistant message the current stream writes to.
     *
     * One run owns one message, so a resumed run keeps appending to the message
     * it paused on even if a later frame omits or changes its message id. A new
     * prompt resets it.
     */
    streamingMessageId: string | null;
  };
  /** Approvals the current run requested, oldest first. */
  approvals: AgentApproval[];
}

/** Transcript of a conversation nothing is known about yet. */
export const EMPTY_TRANSCRIPT: AgentTranscript = {
  messages: [],
  run: { runId: null, status: 'idle', error: null, streamingMessageId: null },
  approvals: [],
};

/**
 * Builds an empty transcript.
 *
 * @returns A fresh transcript that callers may mutate while reducing.
 */
export function emptyTranscript(): AgentTranscript {
  return {
    messages: [],
    run: { runId: null, status: 'idle', error: null, streamingMessageId: null },
    approvals: [],
  };
}

/**
 * Copies a transcript deep enough that a reducer can mutate the copy.
 *
 * The store must publish a new transcript object per event: React compares the
 * snapshot by reference, so reducing the live object in place would leave the
 * chat frozen until something else re-rendered it. Tool calls are copied once
 * and shared between `tools` and `steps`, so a finished call updates both.
 *
 * @param transcript Transcript to copy; the input is not mutated.
 * @returns A transcript the caller may mutate freely.
 */
export function cloneTranscript(transcript: AgentTranscript): AgentTranscript {
  return {
    messages: transcript.messages.map((message) => {
      const tools = message.tools.map((call) => ({ ...call }));
      const copies = new Map<AgentToolCall, AgentToolCall>();
      message.tools.forEach((call, index) => {
        const copy = tools[index];
        if (copy !== undefined) {
          copies.set(call, copy);
        }
      });
      return {
        ...message,
        tools,
        steps: message.steps.map((step) =>
          step.kind === 'tool'
            ? { kind: 'tool', call: copies.get(step.call) ?? step.call }
            : { ...step },
        ),
        resources: message.resources.map((item) => ({ ...item })),
      };
    }),
    run: { ...transcript.run },
    approvals: transcript.approvals.map((item) => ({ ...item })),
  };
}

/**
 * Maps the run status the server reports onto the UI status.
 *
 * @param status Value of a `done` or `message.completed` event.
 * @returns The matching UI status; anything unknown counts as a failure.
 */
function runStatus(status: string): AgentRunStatus {
  switch (status) {
    case 'completed':
      return 'completed';
    case 'interrupted':
      return 'interrupted';
    case 'awaiting_approval':
      return 'awaiting_approval';
    default:
      return 'failed';
  }
}

/**
 * Returns the message a streaming event applies to, creating it when the
 * `message.started` event was missed.
 *
 * @param transcript Transcript being reduced.
 * @param messageId Id carried by the event, or `null`.
 * @param now Timestamp given to a newly created message.
 * @returns The message, which is already part of the transcript.
 */
function streamingMessage(
  transcript: AgentTranscript,
  messageId: string | null,
  now: string,
): AgentMessage {
  const pinned = transcript.run.streamingMessageId;
  const existing =
    (pinned === null
      ? undefined
      : transcript.messages.find((message) => message.messageId === pinned)) ??
    (messageId === null
      ? transcript.messages.findLast((message) => message.streaming)
      : transcript.messages.find((message) => message.messageId === messageId));
  if (existing !== undefined) {
    transcript.run.streamingMessageId = existing.messageId;
    return existing;
  }
  const created: AgentMessage = {
    messageId: messageId ?? `local-assistant-${String(transcript.messages.length)}`,
    role: 'assistant',
    content: '',
    createdAt: now,
    interrupted: false,
    tools: [],
    steps: [],
    resources: [],
    streaming: true,
    reasoning: '',
    stepsCollapsed: false,
    streamStartedAt: null,
    answerStartedAt: null,
    completedAt: null,
  };
  transcript.messages.push(created);
  transcript.run.streamingMessageId = created.messageId;
  return created;
}

/**
 * Returns whether a message already produced a step worth collapsing.
 *
 * @param message Message being reduced.
 * @returns `true` once it streamed thinking or called a tool.
 */
function hasSteps(message: AgentMessage): boolean {
  return message.reasoning !== '' || message.tools.length > 0;
}

/**
 * Applies one streamed event to a transcript.
 *
 * The function mutates its argument, so the store must pass a copy. It is the
 * single place that knows the event protocol, which keeps the components free
 * of protocol details.
 *
 * @param transcript Transcript to update.
 * @param event Decoded event.
 * @param now Timestamp given to messages created by this event.
 * @returns The same transcript, updated.
 */
export function applyAgentEvent(
  transcript: AgentTranscript,
  event: AgentEvent,
  now: string = new Date().toISOString(),
): AgentTranscript {
  if (event.runId !== null) {
    transcript.run.runId = event.runId;
  }

  switch (event.kind) {
    case 'message.started': {
      transcript.run.status = 'streaming';
      streamingMessage(transcript, event.messageId, now);
      return transcript;
    }
    case 'reasoning': {
      const message = streamingMessage(transcript, event.messageId, now);
      message.reasoning += event.delta;
      const last = message.steps.at(-1);
      if (last !== undefined && last.kind === 'reasoning') {
        last.text += event.delta;
      } else {
        message.steps.push({ kind: 'reasoning', text: event.delta });
      }
      message.streaming = true;
      message.streamStartedAt ??= event.at ?? now;
      transcript.run.status = 'streaming';
      return transcript;
    }
    case 'token': {
      const message = streamingMessage(transcript, event.messageId, now);
      message.streamStartedAt ??= event.at ?? now;
      // The trace stays unfolded while the run writes, so the thinking and the
      // tool calls are readable as they happen; `completed` folds it once the
      // final answer is in.
      message.answerStartedAt ??= event.at ?? now;
      message.content += event.delta;
      message.streaming = true;
      transcript.run.status = 'streaming';
      return transcript;
    }
    case 'tool.started': {
      const message = streamingMessage(transcript, event.messageId, now);
      message.streamStartedAt ??= event.at ?? now;
      const call: AgentToolCall = {
        tool: event.tool,
        argsHash: event.argsHash,
        status: 'running',
        durationMs: null,
        errorCode: null,
        argsJson: event.argsJson,
        resultPreview: '',
      };
      message.tools.push(call);
      message.steps.push({ kind: 'tool', call });
      message.streaming = true;
      return transcript;
    }
    case 'tool.finished': {
      const message = streamingMessage(transcript, event.messageId, now);
      const running = message.tools.findLast(
        (call) =>
          call.status === 'running' &&
          call.tool === event.tool &&
          (event.argsHash === '' || call.argsHash === event.argsHash),
      );
      const finished: AgentToolCall = {
        tool: event.tool,
        argsHash: event.argsHash,
        status: toolStatus(event.status),
        durationMs: event.durationMs,
        errorCode: event.errorCode,
        argsJson: event.argsJson,
        resultPreview: event.resultPreview,
      };
      if (running === undefined) {
        message.tools.push(finished);
        message.steps.push({ kind: 'tool', call: finished });
      } else {
        // The step holds the same object, so the card updates in place. A server
        // that omits a preview must not erase the one it already sent.
        Object.assign(running, {
          ...finished,
          argsJson: event.argsJson === '' ? running.argsJson : event.argsJson,
          resultPreview: event.resultPreview === '' ? running.resultPreview : event.resultPreview,
        });
      }
      return transcript;
    }
    case 'resource.read': {
      const message = streamingMessage(transcript, event.messageId, now);
      message.resources.push({
        uri: event.uri,
        sizeBytes: event.sizeBytes,
        mimeType: event.mimeType,
      });
      return transcript;
    }
    case 'approval.required': {
      if (transcript.approvals.some((item) => item.approvalId === event.approvalId)) {
        return transcript;
      }
      transcript.approvals.push({
        approvalId: event.approvalId,
        runId: event.runId,
        tool: event.tool,
        argsHash: event.argsHash,
        reason: event.reason,
        status: 'pending',
      });
      transcript.run.status = 'awaiting_approval';
      return transcript;
    }
    case 'approval.resolved': {
      const approval = transcript.approvals.find((item) => item.approvalId === event.approvalId);
      if (approval !== undefined) {
        approval.status = event.approved ? 'approved' : 'denied';
      }
      return transcript;
    }
    case 'completed': {
      const message = streamingMessage(transcript, event.messageId, now);
      if (event.finalAnswer !== '') {
        message.content = event.finalAnswer;
      }
      if (event.reasoning !== '' && message.reasoning === '') {
        // The completion frame repeats the thinking, so a client that missed
        // the `llm.reasoning` frames still shows it.
        message.reasoning = event.reasoning;
        if (!message.steps.some((step) => step.kind === 'reasoning')) {
          message.steps.unshift({ kind: 'reasoning', text: event.reasoning });
        }
      }
      if (event.status === 'completed' && message.content !== '' && hasSteps(message)) {
        // The final answer is complete, so the trace that produced it folds
        // away; the summary keeps it one click away. A pause does not fold,
        // because the run is not done yet and keeps writing after the decision.
        message.stepsCollapsed = true;
      }
      message.streamStartedAt ??= event.at ?? now;
      message.completedAt = event.at ?? now;
      // The answer is final (or paused); either way no more tokens arrive on
      // this stream.
      message.streaming = false;
      transcript.run.status = runStatus(event.status);
      if (event.status === 'awaiting_approval') {
        // The frame lists every approval of the run; the ones already decided
        // are known here, and a new pause is the only reason to offer a card.
        for (const pending of event.approvals) {
          if (transcript.approvals.some((item) => item.approvalId === pending.approvalId)) {
            continue;
          }
          // The completion frame carries no digest, so the card shows the tool
          // and the reason only.
          transcript.approvals.push({
            approvalId: pending.approvalId,
            runId: event.runId,
            tool: pending.tool,
            argsHash: '',
            reason: pending.reason,
            status: 'pending',
          });
        }
      }
      return transcript;
    }
    case 'error': {
      transcript.run.status = 'failed';
      transcript.run.error = event.message === '' ? 'The run failed.' : event.message;
      for (const message of transcript.messages) {
        message.streaming = false;
        message.completedAt ??= event.at ?? now;
      }
      return transcript;
    }
    case 'done': {
      transcript.run.status = runStatus(event.status);
      for (const message of transcript.messages) {
        message.streaming = false;
        message.completedAt ??= event.at ?? now;
      }
      return transcript;
    }
  }
}

/**
 * Maps the tool status reported by the server onto the UI status.
 *
 * @param status Server status, for example `ok`, `error` or `denied`.
 * @returns The UI status.
 */
function toolStatus(status: string): AgentToolCall['status'] {
  if (status === 'running') {
    return 'running';
  }
  if (status === 'denied') {
    return 'denied';
  }
  return status === 'ok' ? 'ok' : 'error';
}

/**
 * Marks the running answer as interrupted after the caller stopped the stream.
 *
 * @param transcript Transcript to update.
 * @returns The same transcript, updated.
 */
export function markInterrupted(transcript: AgentTranscript): AgentTranscript {
  transcript.run.status = 'interrupted';
  for (const message of transcript.messages) {
    message.streaming = false;
    message.interrupted = message.role === 'assistant' ? true : message.interrupted;
  }
  return transcript;
}

/**
 * Unfolds the trace of a message that a resumed run keeps writing to.
 *
 * A paused run folds its trace when it pauses; approving the call resumes the
 * same message, and the reader wants to watch the remaining steps as they
 * happen, so the trace opens again and folds when the answer is final.
 *
 * @param transcript Transcript to update.
 * @param messageId Message the resumed run writes to, or `null`.
 * @returns The same transcript, updated.
 */
export function unfoldSteps(
  transcript: AgentTranscript,
  messageId: string | null,
): AgentTranscript {
  const message = transcript.messages.find((item) => item.messageId === messageId);
  if (message !== undefined) {
    message.stepsCollapsed = false;
  }
  return transcript;
}

/**
 * Appends an optimistic user message.
 *
 * @param transcript Transcript to update.
 * @param message Message to append.
 * @returns The same transcript, updated.
 */
export function appendUserMessage(
  transcript: AgentTranscript,
  message: AgentMessage,
): AgentTranscript {
  transcript.messages.push(message);
  return transcript;
}

/**
 * Converts a persisted message row into a transcript message.
 *
 * @param row Message as returned by `GET /agent/conversations/{id}/messages`.
 * @returns The transcript message.
 */
export function messageFromRow(row: {
  message_id: string;
  role: string;
  content: string;
  created_at: string;
  interrupted: boolean;
  tools: readonly {
    tool: string;
    args_hash: string;
    status: string;
    duration_ms: number;
    error_code: string | null;
    args_json?: string;
    result_preview?: string;
  }[];
  resources: readonly { uri: string; size_bytes: number; mime_type: string }[];
  reasoning?: string;
}): AgentMessage {
  const tools: AgentToolCall[] = row.tools.map((call) => ({
    tool: call.tool,
    argsHash: call.args_hash,
    status: toolStatus(call.status),
    durationMs: call.duration_ms,
    errorCode: call.error_code,
    argsJson: call.args_json ?? '',
    resultPreview: call.result_preview ?? '',
  }));
  const reasoning = row.reasoning ?? '';
  return {
    messageId: row.message_id,
    role: row.role === 'user' ? 'user' : 'assistant',
    content: row.content,
    createdAt: row.created_at,
    interrupted: row.interrupted,
    tools,
    // The stored row keeps one block of thinking followed by the calls; the
    // interleaving of a live run is not persisted.
    steps: [
      ...(reasoning === '' ? [] : [{ kind: 'reasoning' as const, text: reasoning }]),
      ...tools.map((call) => ({ kind: 'tool' as const, call })),
    ],
    resources: row.resources.map((item) => ({
      uri: item.uri,
      sizeBytes: item.size_bytes,
      mimeType: item.mime_type,
    })),
    streaming: false,
    reasoning,
    // A stored message is finished, so its trace starts folded away.
    stepsCollapsed: tools.length > 0 || reasoning !== '',
    streamStartedAt: null,
    answerStartedAt: null,
    completedAt: row.created_at,
  };
}
