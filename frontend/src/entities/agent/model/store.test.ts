import { beforeEach, describe, expect, it } from 'vitest';

import { parseAgentEvent } from './events';
import { useAgentStore } from './store';
import { emptyTranscript } from './transcript';

const CONVERSATION = 'conv-1';
const RUN = 'run-1';
const MESSAGE = 'msg-1';

/** Decodes one frame, failing the test when the payload is unusable. */
function ev(name: string, payload: Record<string, unknown>) {
  const event = parseAgentEvent(name, JSON.stringify({ run_id: RUN, ...payload }));
  if (event === null) {
    throw new Error(`frame ${name} did not decode`);
  }
  return event;
}

/** Seeds a transcript that paused on one approval. */
function seedPausedTranscript(): void {
  useAgentStore.setState({ transcripts: { [CONVERSATION]: emptyTranscript() } });
  const store = useAgentStore.getState();
  store.beginRun(CONVERSATION);
  store.applyEvent(CONVERSATION, ev('message.started', { message_id: MESSAGE }));
  store.applyEvent(
    CONVERSATION,
    ev('approval.required', {
      approval_id: 'ap-1',
      tool: 'approve_term',
      args_hash: 'h',
      reason: 'no hint',
    }),
  );
  store.applyEvent(
    CONVERSATION,
    ev('message.completed', { status: 'awaiting_approval', final_answer: '' }),
  );
}

describe('agent store', () => {
  beforeEach(() => {
    useAgentStore.setState({
      conversations: [],
      activeConversationId: null,
      transcripts: {},
      collapsedOverrides: {},
      widgetOpen: false,
    });
  });

  it('publishes a new transcript for every event, so the chat re-renders', () => {
    useAgentStore.getState().beginRun(CONVERSATION);
    const before = useAgentStore.getState().transcripts[CONVERSATION];

    useAgentStore
      .getState()
      .applyEvent(CONVERSATION, ev('llm.token', { message_id: MESSAGE, delta: 'hi' }));

    const after = useAgentStore.getState().transcripts[CONVERSATION];
    expect(after).not.toBe(before);
    expect(after?.messages[0]?.content).toBe('hi');
  });

  it('keeps the message and the approvals of a resumed run', () => {
    seedPausedTranscript();
    const paused = useAgentStore.getState().transcripts[CONVERSATION];

    useAgentStore.getState().beginRun(CONVERSATION, { runId: RUN });
    const resumed = useAgentStore.getState().transcripts[CONVERSATION];

    expect(resumed?.run.status).toBe('streaming');
    expect(resumed?.run.streamingMessageId).toBe(MESSAGE);
    expect(resumed?.approvals.map((item) => item.approvalId)).toEqual(['ap-1']);
    expect(paused?.messages).toHaveLength(1);
  });

  it('unfolds the trace of a resumed run even after the reader folded it', () => {
    seedPausedTranscript();
    const store = useAgentStore.getState();
    store.setStepsCollapsed(MESSAGE, true);

    store.beginRun(CONVERSATION, { runId: RUN });

    const transcript = useAgentStore.getState().transcripts[CONVERSATION];
    expect(transcript?.messages[0]?.stepsCollapsed).toBe(false);
    expect(useAgentStore.getState().collapsedOverrides[MESSAGE]).toBeUndefined();
  });

  it('drops the approvals of the previous run on a new prompt', () => {
    seedPausedTranscript();

    useAgentStore.getState().beginRun(CONVERSATION);
    const started = useAgentStore.getState().transcripts[CONVERSATION];

    expect(started?.approvals).toEqual([]);
    expect(started?.run.streamingMessageId).toBeNull();
  });

  it('writes a resumed run into the message the run paused on', () => {
    seedPausedTranscript();
    const store = useAgentStore.getState();
    store.beginRun(CONVERSATION, { runId: RUN });

    store.applyEvent(
      CONVERSATION,
      ev('tool.finished', { tool: 'approve_term', args_hash: 'h', status: 'ok' }),
    );

    const transcript = useAgentStore.getState().transcripts[CONVERSATION];
    expect(transcript?.messages).toHaveLength(1);
    expect(transcript?.messages[0]?.steps.map((step) => step.kind)).toEqual(['tool']);
  });

  it('rewrites a user message and drops the answer after it', () => {
    useAgentStore.setState({ transcripts: { [CONVERSATION]: emptyTranscript() } });
    const store = useAgentStore.getState();
    store.beginRun(CONVERSATION);
    const userId = store.addUserMessage(CONVERSATION, 'first prompt');
    store.applyEvent(CONVERSATION, ev('message.started', { message_id: MESSAGE }));
    store.applyEvent(CONVERSATION, ev('llm.token', { message_id: MESSAGE, delta: 'old answer' }));
    store.applyEvent(
      CONVERSATION,
      ev('message.completed', { status: 'completed', final_answer: 'old answer' }),
    );

    useAgentStore.getState().editUserMessage(CONVERSATION, userId, 'new prompt');

    const transcript = useAgentStore.getState().transcripts[CONVERSATION];
    expect(transcript?.messages.map((message) => message.role)).toEqual(['user']);
    expect(transcript?.messages[0]?.content).toBe('new prompt');
    expect(transcript?.run).toEqual({
      runId: null,
      status: 'idle',
      error: null,
      streamingMessageId: null,
    });
    expect(transcript?.approvals).toEqual([]);
  });

  it('leaves the transcript alone when the message is not a user message', () => {
    seedPausedTranscript();
    const before = useAgentStore.getState().transcripts[CONVERSATION];

    useAgentStore.getState().editUserMessage(CONVERSATION, MESSAGE, 'nope');

    expect(useAgentStore.getState().transcripts[CONVERSATION]).toBe(before);
  });

  it('records the fold the user chose for one message', () => {
    seedPausedTranscript();

    useAgentStore.getState().setStepsCollapsed(MESSAGE, false);

    expect(useAgentStore.getState().collapsedOverrides[MESSAGE]).toBe(false);
  });

  it('restores the cards of a paused run when the conversation is opened', () => {
    useAgentStore.setState({ transcripts: { [CONVERSATION]: emptyTranscript() } });

    useAgentStore.getState().hydrateApprovals(CONVERSATION, [
      {
        approval_id: 'ap-1',
        run_id: RUN,
        tool: 'approve_term',
        args_hash: 'h',
        reason: 'no hint',
        status: 'pending',
        requested_at: '2026-11-15T10:00:00.000Z',
      },
    ]);

    const transcript = useAgentStore.getState().transcripts[CONVERSATION];
    expect(transcript?.approvals.map((item) => item.approvalId)).toEqual(['ap-1']);
    expect(transcript?.run.status).toBe('awaiting_approval');
    expect(transcript?.run.runId).toBe(RUN);
  });

  it('does not resurrect cards over a live stream', () => {
    useAgentStore.getState().beginRun(CONVERSATION);

    useAgentStore.getState().hydrateApprovals(CONVERSATION, [
      {
        approval_id: 'ap-1',
        run_id: RUN,
        tool: 'approve_term',
        args_hash: 'h',
        reason: 'no hint',
        status: 'pending',
        requested_at: '2026-11-15T10:00:00.000Z',
      },
    ]);

    expect(useAgentStore.getState().transcripts[CONVERSATION]?.approvals).toEqual([]);
  });

  it('loads the history even when the approvals landed first', () => {
    // The two queries settle in any order; the approval hydration must not hide
    // the messages that arrive after it.
    useAgentStore.getState().hydrateApprovals(CONVERSATION, [
      {
        approval_id: 'ap-1',
        run_id: RUN,
        tool: 'approve_term',
        args_hash: 'h',
        reason: 'no hint',
        status: 'pending',
        requested_at: '2026-11-15T10:00:00.000Z',
      },
    ]);

    useAgentStore.getState().hydrateMessages(CONVERSATION, [
      {
        message_id: 'msg-1',
        role: 'user',
        content: 'List the business terms that are still drafts',
        interrupted: false,
        created_at: '2026-11-15T10:00:00.000Z',
        resources: [],
        tools: [],
      },
    ]);

    const transcript = useAgentStore.getState().transcripts[CONVERSATION];
    expect(transcript?.messages.map((item) => item.messageId)).toEqual(['msg-1']);
    expect(transcript?.approvals.map((item) => item.approvalId)).toEqual(['ap-1']);
    expect(transcript?.run.status).toBe('awaiting_approval');
  });

  it('keeps the live paused answer when the persisted rows arrive', () => {
    seedPausedTranscript();

    useAgentStore.getState().hydrateMessages(CONVERSATION, []);

    const transcript = useAgentStore.getState().transcripts[CONVERSATION];
    expect(transcript?.messages).toHaveLength(1);
    expect(transcript?.approvals).toHaveLength(1);
  });

  it('drops a card whose run no longer waits for a decision', () => {
    seedPausedTranscript();

    useAgentStore.getState().hydrateApprovals(CONVERSATION, []);

    const transcript = useAgentStore.getState().transcripts[CONVERSATION];
    expect(transcript?.approvals).toEqual([]);
    expect(transcript?.run.status).toBe('completed');
    // The history is untouched: only the stale card and the fake pause go away.
    expect(transcript?.messages).toHaveLength(1);
  });

  it('forgets a deleted conversation, its transcript and the selection', () => {
    seedPausedTranscript();
    useAgentStore.setState({ activeConversationId: CONVERSATION });

    useAgentStore.getState().removeConversation(CONVERSATION);

    const state = useAgentStore.getState();
    expect(state.transcripts[CONVERSATION]).toBeUndefined();
    expect(state.activeConversationId).toBeNull();
  });

  it('defaults to auto-approve and remembers the choice', () => {
    expect(useAgentStore.getState().autoApprove).toBe(true);

    useAgentStore.getState().setAutoApprove(false);

    expect(useAgentStore.getState().autoApprove).toBe(false);
    expect(window.localStorage.getItem('etlalchemy.agent.auto-approve')).toBe('0');

    useAgentStore.getState().setAutoApprove(true);

    expect(window.localStorage.getItem('etlalchemy.agent.auto-approve')).toBe('1');
  });

  it('drops a single card the server refused', () => {
    seedPausedTranscript();

    useAgentStore.getState().dropApproval(CONVERSATION, 'ap-1');

    expect(useAgentStore.getState().transcripts[CONVERSATION]?.approvals).toEqual([]);
  });

  it('keeps only the cards the server still offers', () => {
    // A decision recorded while the stream was gone leaves a card that the server
    // no longer lists; rendering it again would ask for an answer it already has.
    seedPausedTranscript();

    useAgentStore.getState().hydrateApprovals(CONVERSATION, [
      {
        approval_id: 'ap-2',
        run_id: RUN,
        tool: 'add_diagram',
        args_hash: 'h2',
        reason: 'no hint',
        status: 'pending',
        requested_at: '2026-11-15T10:05:00.000Z',
      },
    ]);

    const transcript = useAgentStore.getState().transcripts[CONVERSATION];
    expect(transcript?.approvals.map((item) => item.approvalId)).toEqual(['ap-2']);
    expect(transcript?.run.status).toBe('awaiting_approval');
  });

  it('keeps a decided card as a trace while reconciling', () => {
    seedPausedTranscript();
    useAgentStore
      .getState()
      .applyEvent(CONVERSATION, ev('approval.resolved', { approval_id: 'ap-1', approved: true }));

    useAgentStore.getState().hydrateApprovals(CONVERSATION, []);

    const transcript = useAgentStore.getState().transcripts[CONVERSATION];
    expect(transcript?.approvals.map((item) => item.status)).toEqual(['approved']);
    expect(transcript?.run.status).toBe('completed');
  });

  it('settles a run the server already decided without claiming a failure', () => {
    seedPausedTranscript();
    useAgentStore.getState().failRun(CONVERSATION, 'boom');

    useAgentStore.getState().settleRun(CONVERSATION);

    const transcript = useAgentStore.getState().transcripts[CONVERSATION];
    expect(transcript?.run.status).toBe('idle');
    expect(transcript?.run.error).toBeNull();
    expect(transcript?.run.streamingMessageId).toBeNull();
    // Settling keeps the history and the cards; hydration reconciles them.
    expect(transcript?.messages).toHaveLength(1);
    expect(transcript?.approvals).toHaveLength(1);
  });
});
