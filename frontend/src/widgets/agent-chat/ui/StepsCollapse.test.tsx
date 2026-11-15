import { useState } from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import type { AgentMessage, AgentToolCall } from '@/entities/agent';

import { StepsCollapse } from './StepsCollapse';
import { ReasoningBlock } from './ReasoningBlock';

afterEach(cleanup);

/** Builds an assistant message with a thinking step and one tool call. */
function message(overrides: Partial<AgentMessage> = {}): AgentMessage {
  const tool = call();
  return {
    messageId: 'm',
    role: 'assistant',
    content: 'answer',
    createdAt: '2026-11-15T10:00:00.000Z',
    interrupted: false,
    tools: [tool],
    steps: [
      { kind: 'reasoning', text: 'thinking' },
      { kind: 'tool', call: tool },
    ],
    resources: [],
    streaming: false,
    reasoning: 'thinking',
    stepsCollapsed: true,
    streamStartedAt: '2026-11-15T10:00:00.000Z',
    answerStartedAt: '2026-11-15T10:01:24.000Z',
    completedAt: '2026-11-15T10:01:30.000Z',
    ...overrides,
  };
}

/** Builds one finished tool call. */
function call(): AgentToolCall {
  return {
    tool: 'list_models',
    argsHash: 'h',
    status: 'ok',
    durationMs: 1200,
    errorCode: null,
    argsJson: '{}',
    resultPreview: '[]',
  };
}

/** Wrapper that owns the fold, like the transcript does. */
function Foldable({ initial }: { initial: boolean }) {
  const [collapsed, setCollapsed] = useState(initial);
  return (
    <StepsCollapse
      message={message()}
      collapsed={collapsed}
      onToggle={() => {
        setCollapsed(!collapsed);
      }}
    >
      <ReasoningBlock text="thinking" streaming={false} />
      <p>tool card</p>
    </StepsCollapse>
  );
}

describe('StepsCollapse', () => {
  it('hides the steps while folded', () => {
    render(<Foldable initial />);

    expect(screen.getByRole('button', { expanded: false })).toHaveTextContent('Ran 2 steps');
    expect(screen.queryByText('thinking')).not.toBeInTheDocument();
    expect(screen.queryByText('tool card')).not.toBeInTheDocument();
  });

  it('opens the steps and closes them again', async () => {
    render(<Foldable initial={false} />);

    expect(screen.getByText('thinking')).toBeInTheDocument();
    expect(screen.getByText('tool card')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { expanded: true }));

    expect(screen.getByRole('button', { expanded: false })).toBeInTheDocument();
  });
});

describe('ReasoningBlock', () => {
  it('renders nothing without thinking', () => {
    const { container } = render(<ReasoningBlock text="" />);

    expect(container).toBeEmptyDOMElement();
  });

  it('marks the caret only while the model is still thinking', () => {
    render(<ReasoningBlock text="thinking" streaming />);

    expect(screen.getByLabelText('The model is still thinking')).toBeInTheDocument();
    expect(screen.getByText(/thinking/)).toBeInTheDocument();
  });
});
