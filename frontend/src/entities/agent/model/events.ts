/** Fields every server-sent event carries in its `data` payload. */
interface Envelope {
  /** Run that produced the event, when the server sent one. */
  runId: string | null;
  /** Assistant message the event belongs to, when the server sent one. */
  messageId: string | null;
  /** Monotonic position of the event inside the run. */
  seq: number | null;
  /** Moment the server produced the event, when it sent one. */
  at: string | null;
}

/** `message.started`: the assistant message is about to receive tokens. */
export type MessageStartedEvent = Envelope & { kind: 'message.started' };

/** `llm.reasoning`: one streamed chunk of the model's thinking. */
export type ReasoningEvent = Envelope & { kind: 'reasoning'; delta: string };

/** `llm.token`: one streamed chunk of the answer. */
export type TokenEvent = Envelope & { kind: 'token'; delta: string };

/** `tool.started`: an MCP tool call began. */
export type ToolStartedEvent = Envelope & {
  kind: 'tool.started';
  tool: string;
  argsHash: string;
  /** Redacted, truncated JSON of the arguments. */
  argsJson: string;
};

/** `tool.finished`: an MCP tool call returned. */
export type ToolFinishedEvent = Envelope & {
  kind: 'tool.finished';
  tool: string;
  argsHash: string;
  status: string;
  durationMs: number;
  errorCode: string | null;
  /** Redacted, truncated JSON of the arguments. */
  argsJson: string;
  /** Truncated text the tool returned. */
  resultPreview: string;
};

/** `resource.read`: the agent read one MCP resource. */
export type ResourceReadEvent = Envelope & {
  kind: 'resource.read';
  uri: string;
  sizeBytes: number;
  mimeType: string;
};

/** `approval.required`: the run paused and waits for a human decision. */
export type ApprovalRequiredEvent = Envelope & {
  kind: 'approval.required';
  approvalId: string;
  tool: string;
  argsHash: string;
  reason: string;
};

/** `approval.resolved`: the decision was recorded. */
export type ApprovalResolvedEvent = Envelope & {
  kind: 'approval.resolved';
  approvalId: string;
  approved: boolean;
};

/** `message.completed`: the assistant message is finished or paused. */
export type MessageCompletedEvent = Envelope & {
  kind: 'completed';
  status: string;
  finalAnswer: string;
  /** Number of tool calls in the trace. */
  toolsCalled: number;
  /** Number of resources read in the trace. */
  resourcesAccessed: number;
  /** Thinking the run streamed, so a client that missed frames can fill it in. */
  reasoning: string;
  /** Approvals of the run, so a client that missed the pause still sees them. */
  approvals: { approvalId: string; tool: string; reason: string }[];
};

/** `error`: the run failed. */
export type ErrorEvent = Envelope & { kind: 'error'; message: string };

/** `done`: the run reached a terminal status. */
export type DoneEvent = Envelope & { kind: 'done'; status: string };

/** One decoded event of an agent run. */
export type AgentEvent =
  | MessageStartedEvent
  | ReasoningEvent
  | TokenEvent
  | ToolStartedEvent
  | ToolFinishedEvent
  | ResourceReadEvent
  | ApprovalRequiredEvent
  | ApprovalResolvedEvent
  | MessageCompletedEvent
  | ErrorEvent
  | DoneEvent;

/**
 * Reads a string field.
 *
 * @param data Decoded payload.
 * @param key Field name.
 * @returns The value, or an empty string when it is missing or not a string.
 */
function text(data: Record<string, unknown>, key: string): string {
  const value = data[key];
  return typeof value === 'string' ? value : '';
}

/**
 * Reads an optional string field.
 *
 * @param data Decoded payload.
 * @param key Field name.
 * @returns The value, or `null` when it is missing or not a string.
 */
function optionalText(data: Record<string, unknown>, key: string): string | null {
  const value = data[key];
  return typeof value === 'string' && value !== '' ? value : null;
}

/**
 * Reads a numeric field.
 *
 * @param data Decoded payload.
 * @param key Field name.
 * @returns The value, or `0` when it is missing or not a number.
 */
function count(data: Record<string, unknown>, key: string): number {
  const value = data[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

/**
 * Reads the size of a trace list, accepting both a list and a count.
 *
 * @param data Decoded payload.
 * @param key Field name.
 * @returns The number of entries, or `0` when the field is missing.
 */
function size(data: Record<string, unknown>, key: string): number {
  const value = data[key];
  if (Array.isArray(value)) {
    return value.length;
  }
  return count(data, key);
}

/**
 * Reads a boolean field.
 *
 * @param data Decoded payload.
 * @param key Field name.
 * @returns The value, or `false` when it is missing or not a boolean.
 */
function flag(data: Record<string, unknown>, key: string): boolean {
  return data[key] === true;
}

/**
 * Reads the approval list of a `message.completed` payload.
 *
 * @param data Decoded payload.
 * @returns The approvals, `[]` when the field is missing or malformed.
 */
function approvals(
  data: Record<string, unknown>,
): { approvalId: string; tool: string; reason: string }[] {
  const value = data.approvals;
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((item: unknown) => {
    if (item === null || typeof item !== 'object') {
      return [];
    }
    const approval = item as Record<string, unknown>;
    const approvalId = text(approval, 'approval_id');
    return approvalId === ''
      ? []
      : [{ approvalId, tool: text(approval, 'tool'), reason: text(approval, 'reason') }];
  });
}

/**
 * Decodes one SSE frame into an agent event.
 *
 * Unknown event names and malformed payloads answer `null` instead of raising,
 * so a newer server can add events without breaking an older client.
 *
 * @param name Value of the `event:` field.
 * @param payload Value of the `data:` field, a JSON object.
 * @returns The decoded event, or `null` when it is unknown or unusable.
 */
export function parseAgentEvent(name: string, payload: string): AgentEvent | null {
  let decoded: unknown;
  try {
    decoded = JSON.parse(payload) as unknown;
  } catch {
    return null;
  }
  if (decoded === null || typeof decoded !== 'object') {
    return null;
  }
  const data = decoded as Record<string, unknown>;
  const envelope: Envelope = {
    runId: optionalText(data, 'run_id'),
    messageId: optionalText(data, 'message_id'),
    seq: typeof data.seq === 'number' ? data.seq : null,
    at: optionalText(data, 'timestamp'),
  };

  switch (name) {
    case 'message.started':
      return { ...envelope, kind: 'message.started' };
    case 'llm.reasoning':
      return { ...envelope, kind: 'reasoning', delta: text(data, 'delta') };
    case 'llm.token':
      return { ...envelope, kind: 'token', delta: text(data, 'delta') };
    case 'tool.started':
      return {
        ...envelope,
        kind: 'tool.started',
        tool: text(data, 'tool'),
        argsHash: text(data, 'args_hash'),
        argsJson: text(data, 'args_json'),
      };
    case 'tool.finished':
      return {
        ...envelope,
        kind: 'tool.finished',
        tool: text(data, 'tool'),
        argsHash: text(data, 'args_hash'),
        status: text(data, 'status'),
        durationMs: count(data, 'duration_ms'),
        errorCode: optionalText(data, 'error_code'),
        argsJson: text(data, 'args_json'),
        resultPreview: text(data, 'result_preview'),
      };
    case 'resource.read':
      return {
        ...envelope,
        kind: 'resource.read',
        uri: text(data, 'uri'),
        sizeBytes: count(data, 'size_bytes'),
        mimeType: text(data, 'mime_type'),
      };
    case 'approval.required':
      return {
        ...envelope,
        kind: 'approval.required',
        approvalId: text(data, 'approval_id'),
        tool: text(data, 'tool'),
        argsHash: text(data, 'args_hash'),
        reason: text(data, 'reason'),
      };
    case 'approval.resolved':
      return {
        ...envelope,
        kind: 'approval.resolved',
        approvalId: text(data, 'approval_id'),
        approved: flag(data, 'approved'),
      };
    case 'message.completed':
      return {
        ...envelope,
        kind: 'completed',
        status: text(data, 'status'),
        finalAnswer: text(data, 'final_answer'),
        toolsCalled: size(data, 'tools_called'),
        resourcesAccessed: size(data, 'resources_accessed'),
        reasoning: text(data, 'reasoning'),
        approvals: approvals(data),
      };
    case 'error':
      return { ...envelope, kind: 'error', message: text(data, 'message') };
    case 'done':
      return { ...envelope, kind: 'done', status: text(data, 'status') };
    default:
      return null;
  }
}
