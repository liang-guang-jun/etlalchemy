import { apiError, extractDetail, type ApiError } from './error';

/** One frame of a `text/event-stream` response. */
export interface SseFrame {
  /** `id:` value, or `null` when the server omitted it. */
  id: string | null;
  /** `event:` value; the SSE default is `message`. */
  event: string;
  /** `data:` lines joined with a newline. */
  data: string;
}

/** Events and the tail of an incomplete frame. */
export interface SseParseResult {
  frames: SseFrame[];
  rest: string;
}

/** Default event name of the SSE specification. */
const DEFAULT_EVENT = 'message';

/**
 * Splits a decoded chunk into complete frames.
 *
 * A frame ends with a blank line, so anything after the last separator stays in
 * `rest` until more bytes arrive. Comment lines (`: ping`) carry no data and
 * are dropped.
 *
 * @param buffer Bytes decoded so far, including the tail of a previous call.
 * @returns The complete frames and the incomplete tail.
 */
export function parseSseBuffer(buffer: string): SseParseResult {
  const frames: SseFrame[] = [];
  const blocks = buffer.split(/\r?\n\r?\n/);
  const rest = blocks.pop() ?? '';

  for (const block of blocks) {
    if (block.trim() === '') {
      continue;
    }
    let id: string | null = null;
    let event = DEFAULT_EVENT;
    const data: string[] = [];
    for (const line of block.split(/\r?\n/)) {
      if (line === '' || line.startsWith(':')) {
        continue;
      }
      const separator = line.indexOf(':');
      const field = separator === -1 ? line : line.slice(0, separator);
      // A single space after the colon belongs to the syntax, not the value.
      const raw = separator === -1 ? '' : line.slice(separator + 1);
      const value = raw.startsWith(' ') ? raw.slice(1) : raw;
      if (field === 'id') {
        id = value;
      } else if (field === 'event') {
        event = value === '' ? DEFAULT_EVENT : value;
      } else if (field === 'data') {
        data.push(value);
      }
    }
    if (data.length === 0) {
      // A keep-alive or a lone `retry:` line: nothing for the caller to apply.
      continue;
    }
    frames.push({ id, event, data: data.join('\n') });
  }

  return { frames, rest };
}

/** Options of {@link openEventStream}. */
export interface EventStreamOptions {
  /** JSON body sent with the `POST`. */
  body?: unknown;
  /** Bearer token, or `null` when the caller has none. */
  token?: string | null;
  /** Request id echoed by the server log. */
  requestId?: string;
  /** Cancels the stream; aborting it surfaces as an `AbortError`. */
  signal?: AbortSignal;
  /** Receives every complete frame in order. */
  onFrame: (frame: SseFrame) => void;
}

/**
 * Opens a server-sent event stream and feeds its frames to a callback.
 *
 * `EventSource` cannot send a JSON body or an `Authorization` header, so the
 * stream is read from `fetch` and framed here instead.
 *
 * @param url Endpoint that answers `text/event-stream`.
 * @param options Body, credentials, cancellation and the frame callback.
 * @throws ApiError When the server answers with an error status.
 */
export async function openEventStream(url: string, options: EventStreamOptions): Promise<void> {
  const headers: Record<string, string> = {
    Accept: 'text/event-stream',
    'Content-Type': 'application/json',
  };
  if (options.token !== undefined && options.token !== null && options.token !== '') {
    headers.Authorization = `Bearer ${options.token}`;
  }
  if (options.requestId !== undefined) {
    headers['X-Request-ID'] = options.requestId;
  }

  const response = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(options.body ?? {}),
    signal: options.signal ?? null,
  });

  if (!response.ok) {
    const payload: unknown = await readErrorBody(response);
    throw apiError(
      kindForStatus(response.status),
      extractDetail(payload),
      response.status,
    ) as ApiError;
  }
  if (response.body === null) {
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    for (;;) {
      const chunk = await reader.read();
      if (chunk.done) {
        break;
      }
      buffer += decoder.decode(chunk.value, { stream: true });
      const parsed = parseSseBuffer(buffer);
      buffer = parsed.rest;
      for (const frame of parsed.frames) {
        options.onFrame(frame);
      }
    }
    const tail = parseSseBuffer(`${buffer}\n\n`);
    for (const frame of tail.frames) {
      options.onFrame(frame);
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Reads the JSON error body of a failed stream request.
 *
 * @param response Failed response.
 * @returns The parsed body, or `null` when it is not JSON.
 */
async function readErrorBody(response: Response): Promise<unknown> {
  try {
    return (await response.json()) as unknown;
  } catch {
    return null;
  }
}

/**
 * Maps an HTTP status onto the shared error categories.
 *
 * @param status HTTP status of the failed request.
 * @returns The category used by {@link apiError}.
 */
function kindForStatus(status: number): ApiError['kind'] {
  switch (status) {
    case 400:
    case 422:
      return 'validation';
    case 401:
      return 'unauthorized';
    case 403:
      return 'forbidden';
    case 404:
      return 'not_found';
    case 409:
      return 'conflict';
    default:
      return 'unknown';
  }
}

/**
 * Checks whether a thrown value is the cancellation of a stream.
 *
 * @param error Value thrown by {@link openEventStream}.
 * @returns `true` when the caller aborted the request.
 */
export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}
