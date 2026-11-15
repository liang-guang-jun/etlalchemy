import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { send } = vi.hoisted(() => ({ send: vi.fn() }));

vi.mock('@/entities/agent', () => ({
  useRunStatus: () => 'idle',
}));

vi.mock('../model/use-agent-chat', () => ({
  useAgentChat: () => ({ send, stop: vi.fn(), running: false, error: null }),
}));

import { Composer } from './Composer';

beforeEach(() => {
  send.mockClear();
});

afterEach(cleanup);

describe('Composer', () => {
  it('sends the page context of the widget as its own field', async () => {
    render(<Composer conversationId="c1" contextNote={'Data catalog › table contacts'} />);

    await userEvent.type(screen.getByLabelText('Message the agent'), 'why not?{Enter}');

    expect(send).toHaveBeenCalledWith('why not?', {
      pageContext: 'Data catalog › table contacts',
    });
  });

  it('sends a bare prompt when there is no context', async () => {
    render(<Composer conversationId="c1" />);

    await userEvent.type(screen.getByLabelText('Message the agent'), 'hello{Enter}');

    expect(send).toHaveBeenCalledWith('hello', { pageContext: null });
  });
});
