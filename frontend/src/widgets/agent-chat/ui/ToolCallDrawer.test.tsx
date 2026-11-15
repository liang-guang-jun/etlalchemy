import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { AgentToolCall } from '@/entities/agent';

import { ToolCallDrawer } from './ToolCallDrawer';

afterEach(cleanup);

/** Builds one finished tool call with previews. */
function call(overrides: Partial<AgentToolCall> = {}): AgentToolCall {
  return {
    tool: 'catalog_list_tables',
    argsHash: 'abc123',
    status: 'ok',
    durationMs: 42,
    errorCode: null,
    argsJson: '{"catalog":"crm"}',
    resultPreview: '[]',
    ...overrides,
  };
}

describe('ToolCallDrawer', () => {
  it('shows the arguments and the result', () => {
    render(<ToolCallDrawer call={call()} onClose={vi.fn()} />);

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('Arguments')).toBeInTheDocument();
    expect(screen.getByText(/"catalog": "crm"/)).toBeInTheDocument();
    expect(screen.getByText('[]')).toBeInTheDocument();
    expect(screen.getByText('42 ms')).toBeInTheDocument();
    expect(screen.getByText(/abc123/)).toBeInTheDocument();
  });

  it('explains an empty result instead of showing a blank box', () => {
    render(
      <ToolCallDrawer call={call({ resultPreview: '', status: 'running' })} onClose={vi.fn()} />,
    );

    expect(screen.getByText('The tool is still running.')).toBeInTheDocument();
  });

  it('shows a note when no arguments were recorded', () => {
    render(<ToolCallDrawer call={call({ argsJson: '' })} onClose={vi.fn()} />);

    expect(screen.getByText('No arguments were recorded.')).toBeInTheDocument();
  });

  it('closes from the close button', async () => {
    const onClose = vi.fn();
    render(<ToolCallDrawer call={call()} onClose={onClose} />);

    await userEvent.click(screen.getByRole('button', { name: 'Close' }));

    expect(onClose).toHaveBeenCalled();
  });

  it('renders nothing without a selected call', () => {
    render(<ToolCallDrawer call={null} onClose={vi.fn()} />);

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
