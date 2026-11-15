import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { AgentMessage, AgentTranscript } from '@/entities/agent';

import { MessageList } from './MessageList';

// The names come from the read model; the answer tests resolve them on their own.
vi.mock('@/features/agent-chat/model/use-urn-labels', () => ({
  useUrnLabels: () => new Map([['urn:catalog/c1/schema/sales/table/contacts', 'contacts']]),
}));

afterEach(cleanup);

/** Builds one finished assistant message. */
function assistant(content: string): AgentMessage {
  return {
    messageId: 'm1',
    role: 'assistant',
    content,
    createdAt: '2026-11-15T10:00:00.000Z',
    interrupted: false,
    tools: [],
    steps: [],
    resources: [],
    streaming: false,
    reasoning: '',
    stepsCollapsed: true,
    streamStartedAt: null,
    answerStartedAt: null,
    completedAt: '2026-11-15T10:00:05.000Z',
  };
}

/** Builds a transcript holding one message. */
function transcriptOf(message: AgentMessage): AgentTranscript {
  return {
    messages: [message],
    run: { runId: 'r1', status: 'completed', error: null, streamingMessageId: null },
    approvals: [],
  };
}

/**
 * Renders the list inside the router the answer links need.
 *
 * @param content Markdown of the assistant message.
 * @param compact Whether the compact widget styling is used.
 * @param onOpenFullScreen Callback of the full-screen hint.
 * @returns The rendered container.
 */
function renderList(content: string, compact: boolean, onOpenFullScreen?: () => void) {
  return render(
    <MemoryRouter>
      <MessageList
        conversationId="c1"
        transcript={transcriptOf(assistant(content))}
        compact={compact}
        onOpenFullScreen={onOpenFullScreen}
      />
    </MemoryRouter>,
  );
}

describe('MessageList in the compact widget', () => {
  it('renders a table instead of a plain-text excerpt', () => {
    renderList('| field | type |\n| --- | --- |\n| id | uuid |', true);

    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'field' })).toBeInTheDocument();
    expect(screen.queryByText(/open the full screen to read it/i)).not.toBeInTheDocument();
  });

  it('renders a code block and its emphasis', () => {
    const { container } = renderList('Run **this**:\n\n```sql\nselect 1\n```', true);

    expect(container.querySelector('pre code')).toHaveTextContent('select 1');
    expect(screen.getByText('this').tagName).toBe('STRONG');
  });

  it('turns an object URN into a link named after the object', () => {
    renderList('The table urn:catalog/c1/schema/sales/table/contacts is safe.', true);

    const link = screen.getByRole('link', { name: 'contacts' });
    expect(link).toHaveAttribute('href', '/catalog/c1/schemas/sales/tables/contacts');
  });

  it('links a URN the model wrapped in backticks', () => {
    renderList('- 新建表 `test`（`urn:catalog/c1/schema/sales/table/contacts`）', true);

    expect(screen.getByRole('link', { name: 'contacts' })).toHaveAttribute(
      'href',
      '/catalog/c1/schemas/sales/tables/contacts',
    );
  });

  it('keeps the short id while the name is unknown', () => {
    const table = '96420819-4423-4a71-abb2-cc1432e02b6a';

    renderList(`The table urn:catalog/c1/schema/sales/table/${table} is safe.`, true);

    expect(screen.getByRole('link', { name: `${table.slice(0, 8)}…` })).toBeInTheDocument();
  });

  it('keeps a way to the full page for a wide answer', () => {
    renderList('| a |\n| --- |', true, () => {
      // The page opens the same conversation; the list only offers the button.
    });

    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /open full screen/i })).toBeInTheDocument();
  });
});

/** Builds one user message. */
function user(content: string): AgentMessage {
  return { ...assistant(content), messageId: 'u1', role: 'user' };
}

describe('message actions', () => {
  it('copies any message to the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    });
    render(
      <MemoryRouter>
        <MessageList
          conversationId="c1"
          transcript={{
            ...transcriptOf(user('hello')),
            messages: [user('hello'), assistant('hi')],
          }}
        />
      </MemoryRouter>,
    );

    const buttons = screen.getAllByRole('button', { name: 'Copy message' });
    expect(buttons).toHaveLength(2);
    await userEvent.click(buttons[0] as HTMLElement);

    expect(writeText).toHaveBeenCalledWith('hello');
  });

  it('edits a user message and hands the new body to the surface', async () => {
    const onEditMessage = vi.fn();
    render(
      <MemoryRouter>
        <MessageList
          conversationId="c1"
          transcript={{
            ...transcriptOf(user('hello')),
            messages: [user('hello'), assistant('hi')],
          }}
          onEditMessage={onEditMessage}
        />
      </MemoryRouter>,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Edit message' }));
    const editor = screen.getByRole('textbox', { name: 'Edit message' });
    await userEvent.clear(editor);
    await userEvent.type(editor, 'hello again');
    await userEvent.click(screen.getByRole('button', { name: 'Save and regenerate' }));

    expect(onEditMessage).toHaveBeenCalledWith('u1', 'hello again');
    expect(screen.queryByRole('textbox', { name: 'Edit message' })).not.toBeInTheDocument();
  });

  it('offers no edit action without a callback', () => {
    render(
      <MemoryRouter>
        <MessageList conversationId="c1" transcript={transcriptOf(user('hello'))} />
      </MemoryRouter>,
    );

    expect(screen.queryByRole('button', { name: 'Edit message' })).not.toBeInTheDocument();
  });
});
