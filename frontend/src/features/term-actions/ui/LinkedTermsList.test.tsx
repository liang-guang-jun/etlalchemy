import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { TermSummary } from '@/entities/term';

const mocks = vi.hoisted(() => ({
  refetch: vi.fn(),
  unlink: vi.fn(),
  link: vi.fn(),
  terms: [] as TermSummary[],
}));

vi.mock('@/entities/term', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/entities/term')>();
  return {
    ...actual,
    useTermsForTarget: () => ({
      data: mocks.terms,
      isPending: false,
      isError: false,
      error: null,
      refetch: mocks.refetch,
    }),
  };
});

vi.mock('../api/mutation', () => ({
  useUnlinkTerm: () => ({ mutate: mocks.unlink, isPending: false }),
  useLinkTerm: () => ({ mutate: mocks.link, isPending: false, error: null }),
}));

vi.mock('./TermTree', () => ({ TermTree: () => <div data-testid="term-tree" /> }));

import { LinkedTermsList } from './LinkedTermsList';

/** Builds one linked term. */
function term(name: string, status = 'draft'): TermSummary {
  return {
    term_id: `id-${name}`,
    domain_id: 'd1',
    parent_id: null,
    path: name,
    name,
    definition: 'definition',
    status,
    color: '',
  };
}

/** Renders the list on a field. */
function renderList() {
  return render(
    <MemoryRouter>
      <LinkedTermsList targetId="table-1" targetKind="field" fieldName="amount" />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mocks.refetch.mockClear();
  mocks.unlink.mockClear();
  mocks.link.mockClear();
  mocks.terms = [term('ARR')];
});

afterEach(cleanup);

describe('LinkedTermsList', () => {
  it('lists the linked terms with the link action', () => {
    renderList();

    expect(screen.getByRole('link', { name: 'ARR' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Link term' })).toBeInTheDocument();
  });

  it('refreshes the list as soon as the unlink is recorded', async () => {
    renderList();

    await userEvent.click(screen.getByRole('button', { name: 'Unlink ARR' }));

    expect(mocks.unlink).toHaveBeenCalledWith(
      { target_id: 'table-1', target_kind: 'field', field_name: 'amount' },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
    const call = mocks.unlink.mock.calls[0]?.[1] as { onSuccess: () => void };
    expect(mocks.refetch).not.toHaveBeenCalled();

    call.onSuccess();

    expect(mocks.refetch).toHaveBeenCalledTimes(1);
  });

  it('opens the term picker from the link action', async () => {
    renderList();

    await userEvent.click(screen.getByRole('button', { name: 'Link term' }));

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByTestId('term-tree')).toBeInTheDocument();
  });

  it('keeps the unlink action disabled for a term that is not a draft', () => {
    mocks.terms = [term('ARR', 'approved')];
    renderList();

    expect(screen.getByRole('button', { name: 'Unlink ARR' })).toBeDisabled();
  });
});
