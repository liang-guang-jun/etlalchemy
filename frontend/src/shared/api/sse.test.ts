import { describe, expect, it, vi } from 'vitest';

import { isAbortError, openEventStream, parseSseBuffer } from './sse';

describe('parseSseBuffer', () => {
  it('parses complete frames and keeps the incomplete tail', () => {
    const buffer =
      'id: 1\nevent: llm.token\ndata: {"delta":"he"}\n\nid: 2\nevent: llm.token\ndata: {"del';

    const { frames, rest } = parseSseBuffer(buffer);

    expect(frames).toHaveLength(1);
    expect(frames[0]).toEqual({
      id: '1',
      event: 'llm.token',
      data: '{"delta":"he"}',
    });
    expect(rest).toBe('id: 2\nevent: llm.token\ndata: {"del');
  });

  it('joins multi-line data and drops keep-alive comments', () => {
    const buffer = ': ping\n\ndata: line one\ndata: line two\n\n';

    const { frames, rest } = parseSseBuffer(buffer);

    expect(rest).toBe('');
    expect(frames).toEqual([{ id: null, event: 'message', data: 'line one\nline two' }]);
  });

  it('reads CRLF separators', () => {
    const { frames } = parseSseBuffer('id: 7\r\nevent: done\r\ndata: {}\r\n\r\n');

    expect(frames).toEqual([{ id: '7', event: 'done', data: '{}' }]);
  });
});

describe('openEventStream', () => {
  /** Builds a streamed response out of the given chunks. */
  function streamResponse(chunks: string[], status = 200): Response {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) {
          controller.enqueue(encoder.encode(chunk));
        }
        controller.close();
      },
    });
    return new Response(body, { status });
  }

  it('decodes frames across chunk boundaries and sends the bearer token', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(
        streamResponse(['id: 1\nevent: llm.token\ndata: {"delta":"a"}', '\n\ndata: tail\n\n']),
      );
    const frames: string[] = [];

    await openEventStream('/agent/x', {
      body: { content: 'hi' },
      token: 'token-1',
      onFrame: (frame) => {
        frames.push(`${frame.event}:${frame.data}`);
      },
    });

    expect(frames).toEqual(['llm.token:{"delta":"a"}', 'message:tail']);
    const [, init] = fetchMock.mock.calls[0] ?? [];
    expect(init?.headers).toMatchObject({ Authorization: 'Bearer token-1' });
    expect(init?.body).toBe(JSON.stringify({ content: 'hi' }));
  });

  it('throws a validation error with the server detail on a rejected request', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'run is running' }), { status: 409 }),
    );

    await expect(
      openEventStream('/agent/x', {
        token: null,
        onFrame: () => undefined,
      }),
    ).rejects.toMatchObject({ kind: 'conflict', status: 409, detail: 'run is running' });
  });

  it('recognises an aborted read', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(
      new DOMException('The operation was aborted.', 'AbortError'),
    );
    const controller = new AbortController();

    const error: unknown = await openEventStream('/agent/x', {
      signal: controller.signal,
      onFrame: () => undefined,
    }).catch((reason: unknown) => reason);

    expect(isAbortError(error)).toBe(true);
  });
});
