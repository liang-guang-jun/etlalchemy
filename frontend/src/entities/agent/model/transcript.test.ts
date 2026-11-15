import { describe, expect, it } from 'vitest';

import { parseAgentEvent } from './events';
import {
  applyAgentEvent,
  cloneTranscript,
  emptyTranscript,
  markInterrupted,
  messageFromRow,
  unfoldSteps,
  type AgentTranscript,
} from './transcript';

const NOW = '2026-11-15T10:00:00.000Z';
const RUN = 'run-1';
const MESSAGE = 'msg-1';

/** Decodes one frame, failing the test when the payload is unusable. */
function ev(name: string, payload: Record<string, unknown>, messageId: string = MESSAGE) {
  const event = parseAgentEvent(
    name,
    JSON.stringify({ run_id: RUN, message_id: messageId, ...payload }),
  );
  if (event === null) {
    throw new Error(`frame ${name} did not decode`);
  }
  return event;
}

/** Reduces a list of raw frames onto a fresh transcript. */
function reduce(frames: [string, Record<string, unknown>][]): AgentTranscript {
  let transcript = emptyTranscript();
  for (const [name, payload] of frames) {
    transcript = applyAgentEvent(transcript, ev(name, payload), NOW);
  }
  return transcript;
}

describe('applyAgentEvent', () => {
  it('appends tokens to one assistant message', () => {
    const transcript = reduce([
      ['message.started', {}],
      ['llm.token', { delta: 'Hello' }],
      ['llm.token', { delta: ' world' }],
    ]);

    expect(transcript.messages).toHaveLength(1);
    expect(transcript.messages[0]).toMatchObject({
      messageId: MESSAGE,
      role: 'assistant',
      content: 'Hello world',
      streaming: true,
    });
    expect(transcript.run.status).toBe('streaming');
    expect(transcript.run.runId).toBe(RUN);
  });

  it('pairs a tool completion with its start instead of adding a second card', () => {
    const transcript = reduce([
      ['tool.started', { tool: 'catalog_list_tables', args_hash: 'abc' }],
      [
        'tool.finished',
        { tool: 'catalog_list_tables', args_hash: 'abc', status: 'ok', duration_ms: 42 },
      ],
    ]);

    expect(transcript.messages[0]?.tools).toEqual([
      {
        tool: 'catalog_list_tables',
        argsHash: 'abc',
        status: 'ok',
        durationMs: 42,
        errorCode: null,
        argsJson: '',
        resultPreview: '',
      },
    ]);
  });

  it('keeps the argument and result previews of a tool call', () => {
    const transcript = reduce([
      ['tool.started', { tool: 'catalog_list_tables', args_hash: 'abc', args_json: '{}' }],
      [
        'tool.finished',
        {
          tool: 'catalog_list_tables',
          args_hash: 'abc',
          status: 'ok',
          duration_ms: 42,
          args_json: '{"catalog": "crm"}',
          result_preview: '[]',
        },
      ],
    ]);

    expect(transcript.messages[0]?.tools[0]).toMatchObject({
      argsJson: '{"catalog": "crm"}',
      resultPreview: '[]',
    });
  });

  it('keeps a preview already received when a later frame omits it', () => {
    const transcript = reduce([
      ['tool.started', { tool: 'list_models', args_hash: 'h', args_json: '{}' }],
      [
        'tool.finished',
        { tool: 'list_models', args_hash: 'h', status: 'ok', result_preview: 'ok' },
      ],
      ['tool.finished', { tool: 'list_models', args_hash: 'h', status: 'ok' }],
    ]);

    expect(transcript.messages[0]?.tools[0]).toMatchObject({
      argsJson: '{}',
      resultPreview: 'ok',
    });
  });

  it('accumulates the thinking of the message', () => {
    const transcript = reduce([
      ['llm.reasoning', { delta: 'Looking at ' }],
      ['llm.reasoning', { delta: 'the catalog.' }],
    ]);

    expect(transcript.messages[0]).toMatchObject({
      reasoning: 'Looking at the catalog.',
      content: '',
      streaming: true,
    });
  });

  it('keeps the steps unfolded while the answer is written', () => {
    const transcript = reduce([
      ['llm.reasoning', { delta: 'thinking' }],
      ['llm.token', { delta: 'The' }],
      ['llm.token', { delta: ' answer' }],
    ]);

    expect(transcript.messages[0]).toMatchObject({
      content: 'The answer',
      stepsCollapsed: false,
      streaming: true,
    });
  });

  it('does not fold a message that only answers', () => {
    const transcript = reduce([
      ['llm.token', { delta: 'Just ' }],
      ['llm.token', { delta: 'an answer.' }],
    ]);

    expect(transcript.messages[0]?.stepsCollapsed).toBe(false);
  });

  it('folds the steps once the final answer is complete', () => {
    const transcript = reduce([
      ['tool.finished', { tool: 'list_models', args_hash: 'h', status: 'ok' }],
      ['llm.token', { delta: 'one' }],
      ['llm.token', { delta: ' two' }],
      ['message.completed', { status: 'completed', final_answer: 'one two' }],
    ]);

    expect(transcript.messages[0]?.stepsCollapsed).toBe(true);
  });

  it('fills the thinking from the completion frame when the deltas were missed', () => {
    const transcript = reduce([
      ['message.completed', { status: 'completed', final_answer: 'done', reasoning: 'thought' }],
      ['done', { status: 'completed' }],
    ]);

    expect(transcript.messages[0]?.reasoning).toBe('thought');
  });

  it('interleaves the thinking segments and the tool calls', () => {
    const transcript = reduce([
      ['llm.reasoning', { delta: 'first ' }],
      ['llm.reasoning', { delta: 'thought' }],
      ['tool.started', { tool: 'list_models', args_hash: 'a' }],
      ['tool.finished', { tool: 'list_models', args_hash: 'a', status: 'ok' }],
      ['llm.reasoning', { delta: 'second thought' }],
      ['tool.started', { tool: 'list_terms', args_hash: 'b' }],
    ]);

    const steps = transcript.messages[0]?.steps ?? [];
    expect(steps.map((step) => (step.kind === 'reasoning' ? step.text : step.call.tool))).toEqual([
      'first thought',
      'list_models',
      'second thought',
      'list_terms',
    ]);
    // The flat lists stay usable by the timing helpers.
    expect(transcript.messages[0]?.tools).toHaveLength(2);
    expect(transcript.messages[0]?.reasoning).toBe('first thoughtsecond thought');
  });

  it('keeps one message per run when the frames name no message', () => {
    const transcript = emptyTranscript();
    let reduced = applyAgentEvent(transcript, ev('message.started', { message_id: MESSAGE }), NOW);
    reduced = applyAgentEvent(
      reduced,
      parseAgentEvent('tool.started', JSON.stringify({ tool: 'a', args_hash: '1' })) ??
        ev('done', {}),
      NOW,
    );
    reduced = applyAgentEvent(
      reduced,
      parseAgentEvent('tool.started', JSON.stringify({ tool: 'b', args_hash: '2' })) ??
        ev('done', {}),
      NOW,
    );

    expect(reduced.messages).toHaveLength(1);
    expect(reduced.messages[0]?.tools.map((call) => call.tool)).toEqual(['a', 'b']);
    expect(reduced.run.streamingMessageId).toBe(MESSAGE);
  });

  it('offers a completion frame approval only while the run waits', () => {
    const paused = reduce([
      [
        'message.completed',
        {
          status: 'awaiting_approval',
          approvals: [{ approval_id: 'ap-1', tool: 'approve_term', reason: 'no hint' }],
        },
      ],
    ]);
    const finished = reduce([
      ['message.completed', { status: 'completed', final_answer: 'ok' }],
      ['done', { status: 'completed' }],
    ]);

    expect(paused.approvals.map((item) => item.approvalId)).toEqual(['ap-1']);
    expect(finished.approvals).toEqual([]);
  });

  it('pairs by tool name when the server omits the digest', () => {
    const transcript = reduce([
      ['tool.started', { tool: 'search_fields', args_hash: 'abc' }],
      ['tool.finished', { tool: 'search_fields', status: 'error', error_code: '[conflict]' }],
    ]);

    expect(transcript.messages[0]?.tools).toHaveLength(1);
    expect(transcript.messages[0]?.tools[0]).toMatchObject({
      status: 'error',
      errorCode: '[conflict]',
    });
  });

  it('records a resource read', () => {
    const transcript = reduce([
      ['resource.read', { uri: 'catalog:///all', size_bytes: 128, mime_type: 'application/json' }],
    ]);

    expect(transcript.messages[0]?.resources).toEqual([
      { uri: 'catalog:///all', sizeBytes: 128, mimeType: 'application/json' },
    ]);
  });

  it('pauses on an approval and resumes the same message after the decision', () => {
    const paused = reduce([
      ['llm.token', { delta: 'Let me check.' }],
      [
        'approval.required',
        { approval_id: 'ap-1', tool: 'catalog_discard_table', args_hash: 'zz', reason: 'writes' },
      ],
      ['message.completed', { status: 'awaiting_approval', final_answer: '' }],
    ]);

    expect(paused.run.status).toBe('awaiting_approval');
    expect(paused.approvals).toEqual([
      {
        approvalId: 'ap-1',
        runId: RUN,
        tool: 'catalog_discard_table',
        argsHash: 'zz',
        reason: 'writes',
        status: 'pending',
      },
    ]);
    expect(paused.messages[0]?.streaming).toBe(false);

    let resumed = applyAgentEvent(
      paused,
      ev('approval.resolved', { approval_id: 'ap-1', approved: true }),
      NOW,
    );
    resumed = applyAgentEvent(resumed, ev('llm.token', { delta: ' Done.' }), NOW);

    expect(resumed.approvals[0]?.status).toBe('approved');
    expect(resumed.messages).toHaveLength(1);
    expect(resumed.messages[0]?.content).toBe('Let me check. Done.');
  });

  it('asks the next destructive call after the previous decision', () => {
    const paused = reduce([
      [
        'approval.required',
        { approval_id: 'ap-1', tool: 'catalog_discard_table', args_hash: 'a', reason: 'writes' },
      ],
      ['message.completed', { status: 'awaiting_approval', final_answer: '' }],
    ]);

    let resumed = applyAgentEvent(
      paused,
      ev('approval.resolved', { approval_id: 'ap-1', approved: true }),
      NOW,
    );
    resumed = applyAgentEvent(
      resumed,
      ev('approval.required', {
        approval_id: 'ap-2',
        tool: 'semantic_add_entity',
        args_hash: 'b',
        reason: 'writes',
      }),
      NOW,
    );

    // The decided card stays as a trace; the new one is the only pending card.
    expect(resumed.approvals.map((item) => [item.approvalId, item.status])).toEqual([
      ['ap-1', 'approved'],
      ['ap-2', 'pending'],
    ]);
    expect(resumed.run.status).toBe('awaiting_approval');
  });

  it('takes the final answer and the terminal status from the completion frames', () => {
    const transcript = reduce([
      ['llm.token', { delta: 'partial' }],
      ['message.completed', { status: 'completed', final_answer: 'final answer' }],
      ['done', { status: 'completed' }],
    ]);

    expect(transcript.messages[0]).toMatchObject({
      content: 'final answer',
      streaming: false,
    });
    expect(transcript.run.status).toBe('completed');
  });

  it('rebuilds the pending approval from the completion frame without duplicating it', () => {
    const transcript = reduce([
      [
        'approval.required',
        { approval_id: 'ap-9', tool: 'catalog_discard_table', args_hash: 'zz', reason: 'writes' },
      ],
      [
        'message.completed',
        {
          status: 'awaiting_approval',
          final_answer: '',
          tools_called: [{ tool: 'catalog_discard_table', status: 'denied' }],
          resources_accessed: [{ uri: 'catalog:///all' }],
          approvals: [
            { approval_id: 'ap-9', tool: 'catalog_discard_table', reason: 'writes' },
            { approval_id: 'ap-10', tool: 'semantic_add_entity', reason: 'writes' },
          ],
        },
      ],
    ]);

    expect(transcript.approvals.map((item) => item.approvalId)).toEqual(['ap-9', 'ap-10']);
    // The first card keeps the digest it learned from approval.required.
    expect(transcript.approvals[0]).toMatchObject({ argsHash: 'zz', status: 'pending' });
  });

  it('keeps an interrupted status reported by the server', () => {
    const transcript = reduce([['done', { status: 'interrupted' }]]);

    expect(transcript.run.status).toBe('interrupted');
  });

  it('surfaces an error frame', () => {
    const transcript = reduce([['error', { message: 'provider unreachable' }]]);

    expect(transcript.run.status).toBe('failed');
    expect(transcript.run.error).toBe('provider unreachable');
  });
});

describe('markInterrupted', () => {
  it('stops every message and flags the answer', () => {
    const transcript = reduce([['llm.token', { delta: 'half an ans' }]]);

    markInterrupted(transcript);

    expect(transcript.run.status).toBe('interrupted');
    expect(transcript.messages[0]).toMatchObject({ streaming: false, interrupted: true });
  });
});

describe('unfoldSteps', () => {
  it('opens the trace of a message a resumed run keeps writing to', () => {
    const transcript = reduce([
      ['tool.finished', { tool: 'list_models', args_hash: 'h', status: 'ok' }],
      ['llm.token', { delta: 'half' }],
      ['message.completed', { status: 'completed', final_answer: 'half' }],
    ]);
    expect(transcript.messages[0]?.stepsCollapsed).toBe(true);

    unfoldSteps(transcript, MESSAGE);

    expect(transcript.messages[0]?.stepsCollapsed).toBe(false);
  });

  it('keeps the steps unfolded while a run waits for a decision', () => {
    const transcript = reduce([
      ['tool.started', { tool: 'discard_catalog', args_hash: 'h' }],
      ['llm.token', { delta: 'half' }],
      ['message.completed', { status: 'awaiting_approval', final_answer: 'half' }],
    ]);

    expect(transcript.messages[0]?.stepsCollapsed).toBe(false);
  });

  it('leaves the transcript alone when the message is unknown', () => {
    const transcript = reduce([
      ['tool.finished', { tool: 'list_models', args_hash: 'h', status: 'ok' }],
      ['message.completed', { status: 'completed', final_answer: 'done' }],
    ]);

    unfoldSteps(transcript, null);
    unfoldSteps(transcript, 'other');

    expect(transcript.messages[0]?.stepsCollapsed).toBe(true);
  });
});

describe('parseAgentEvent', () => {
  it('returns null for an unknown event name', () => {
    expect(parseAgentEvent('llm.thinking', JSON.stringify({ run_id: RUN }))).toBeNull();
  });

  it('returns null for a payload that is not JSON', () => {
    expect(parseAgentEvent('llm.token', 'not-json')).toBeNull();
  });

  it('defaults missing fields instead of raising', () => {
    expect(parseAgentEvent('tool.finished', JSON.stringify({ tool: 'x' }))).toMatchObject({
      kind: 'tool.finished',
      tool: 'x',
      status: '',
      durationMs: 0,
      errorCode: null,
      argsJson: '',
      resultPreview: '',
      runId: null,
      at: null,
    });
  });

  it('decodes the reasoning event and the timestamp', () => {
    expect(
      parseAgentEvent(
        'llm.reasoning',
        JSON.stringify({ run_id: RUN, delta: 'hmm', timestamp: NOW }),
      ),
    ).toMatchObject({ kind: 'reasoning', delta: 'hmm', at: NOW });
  });
});

describe('messageFromRow', () => {
  const row = {
    message_id: MESSAGE,
    conversation_id: 'conv-1',
    role: 'assistant',
    content: 'answer',
    interrupted: false,
    input_tokens: 1,
    output_tokens: 2,
    created_at: NOW,
    resources: [],
    tools: [
      {
        tool: 'list_models',
        args_hash: 'h',
        status: 'ok',
        duration_ms: 5,
        error_code: null,
        args_json: '{}',
        result_preview: '[]',
      },
    ],
    reasoning: 'thought',
  };

  it('restores the stored trace with its fold', () => {
    const message = messageFromRow(row);

    expect(message).toMatchObject({
      reasoning: 'thought',
      stepsCollapsed: true,
      streaming: false,
      completedAt: NOW,
    });
    expect(message.tools[0]).toMatchObject({ argsJson: '{}', resultPreview: '[]' });
    expect(message.steps.map((step) => step.kind)).toEqual(['reasoning', 'tool']);
    // The step and the flat list share one object, so the card and the drawer
    // never disagree.
    expect(message.steps[1]).toMatchObject({ kind: 'tool', call: message.tools[0] });
  });

  it('leaves a plain answer unfolded', () => {
    const message = messageFromRow({ ...row, tools: [], reasoning: '' });

    expect(message.stepsCollapsed).toBe(false);
    expect(message.steps).toEqual([]);
  });
});

describe('cloneTranscript', () => {
  it('copies deeply enough for a reducer to mutate the copy', () => {
    const original = reduce([
      ['llm.reasoning', { delta: 'hmm' }],
      ['tool.started', { tool: 'list_models', args_hash: 'h' }],
    ]);
    const copy = cloneTranscript(original);

    copy.messages[0]!.content = 'changed';
    copy.messages[0]!.tools[0]!.status = 'ok';
    copy.messages[0]!.steps[0] = { kind: 'reasoning', text: 'other' };
    copy.approvals.push({
      approvalId: 'ap',
      runId: null,
      tool: 't',
      argsHash: '',
      reason: '',
      status: 'pending',
    });

    expect(original.messages[0]?.content).toBe('');
    expect(original.messages[0]?.tools[0]?.status).toBe('running');
    expect(original.messages[0]?.steps[0]).toMatchObject({ text: 'hmm' });
    expect(original.approvals).toEqual([]);
  });

  it('keeps the tool step pointing at the copied call', () => {
    const original = reduce([['tool.started', { tool: 'list_models', args_hash: 'h' }]]);
    const copy = cloneTranscript(original);

    expect(copy.messages[0]?.steps[0]).toMatchObject({ kind: 'tool' });
    const step = copy.messages[0]?.steps[0];
    expect(step?.kind === 'tool' ? step.call : null).toBe(copy.messages[0]?.tools[0]);
  });
});
