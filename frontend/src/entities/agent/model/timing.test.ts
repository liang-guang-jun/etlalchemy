import { describe, expect, it } from 'vitest';

import {
  describeSteps,
  formatDuration,
  stepCount,
  stepsDurationMs,
  toolDurationMs,
} from './timing';
import type { AgentMessage, AgentStep, AgentToolCall } from './transcript';

/** Builds an assistant message with the fields the timings read. */
function message(overrides: Partial<AgentMessage> = {}): AgentMessage {
  return {
    messageId: 'm',
    role: 'assistant',
    content: '',
    createdAt: '2026-11-15T10:00:00.000Z',
    interrupted: false,
    tools: [],
    steps: [],
    resources: [],
    streaming: false,
    reasoning: '',
    stepsCollapsed: false,
    streamStartedAt: null,
    answerStartedAt: null,
    completedAt: null,
    ...overrides,
  };
}

/** Builds one finished tool call. */
function call(durationMs: number | null): AgentToolCall {
  return {
    tool: 'list_models',
    argsHash: 'h',
    status: 'ok',
    durationMs,
    errorCode: null,
    argsJson: '',
    resultPreview: '',
  };
}

/** Builds the trace of one thinking segment and the given calls. */
function traced(tools: AgentToolCall[], reasoning = 'hmm'): AgentStep[] {
  return [
    ...(reasoning === '' ? [] : [{ kind: 'reasoning' as const, text: reasoning }]),
    ...tools.map((item) => ({ kind: 'tool' as const, call: item })),
  ];
}

describe('stepCount', () => {
  it('counts the segments of the trace', () => {
    expect(stepCount(message())).toBe(0);
    expect(stepCount(message({ steps: traced([]) }))).toBe(1);
    const tools = [call(1), call(2)];
    expect(stepCount(message({ tools, steps: traced(tools) }))).toBe(3);
  });
});

describe('toolDurationMs', () => {
  it('sums the finished calls and skips the running one', () => {
    expect(toolDurationMs(message({ tools: [call(1200), call(null), call(300)] }))).toBe(1500);
  });
});

describe('stepsDurationMs', () => {
  it('measures the first event to the first answer token', () => {
    expect(
      stepsDurationMs(
        message({
          streamStartedAt: '2026-11-15T10:00:00.000Z',
          answerStartedAt: '2026-11-15T10:01:24.000Z',
          completedAt: '2026-11-15T10:02:00.000Z',
        }),
      ),
    ).toBe(84_000);
  });

  it('falls back to the completion moment when no token arrived', () => {
    expect(
      stepsDurationMs(
        message({
          streamStartedAt: '2026-11-15T10:00:00.000Z',
          completedAt: '2026-11-15T10:00:02.500Z',
        }),
      ),
    ).toBe(2500);
  });

  it('answers null without timestamps', () => {
    expect(stepsDurationMs(message())).toBeNull();
  });
});

describe('formatDuration', () => {
  it('picks a readable unit', () => {
    expect(formatDuration(840)).toBe('840ms');
    expect(formatDuration(1400)).toBe('1.4s');
    expect(formatDuration(34_000)).toBe('34s');
    expect(formatDuration(84_000)).toBe('1m 24s');
    expect(formatDuration(120_000)).toBe('2m');
  });
});

describe('describeSteps', () => {
  const tools = [call(1200)];
  const tracedMessage = message({
    reasoning: 'hmm',
    tools,
    steps: traced(tools),
    streamStartedAt: '2026-11-15T10:00:00.000Z',
    answerStartedAt: '2026-11-15T10:01:24.000Z',
  });

  it('reports the steps, the tool time and the total', () => {
    expect(describeSteps(tracedMessage)).toBe('Ran 2 steps · tools 1.2s · total 1m 24s');
  });

  it('omits the total when the timestamps are unknown', () => {
    expect(describeSteps({ ...tracedMessage, streamStartedAt: null, answerStartedAt: null })).toBe(
      'Ran 2 steps · tools 1.2s',
    );
  });

  it('uses the singular for one step', () => {
    expect(describeSteps({ ...tracedMessage, steps: traced(tools, '') })).toContain('Ran 1 step ');
  });
});
