import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { TermSearchResult, TermSummary } from '@/entities/term';

const mocks = vi.hoisted(() => ({
  searchData: [] as TermSearchResult[],
  termsData: [] as TermSummary[],
}));

vi.mock('@/entities/domain', () => ({
  useDomains: () => ({
    data: [{ domain_id: 'd1', name: 'Business', description: '' }],
    isPending: false,
    isError: false,
  }),
}));

vi.mock('@/entities/term', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/entities/term')>();
  return {
    ...actual,
    useTerms: () => ({
      data: mocks.termsData,
      isPending: false,
      isError: false,
    }),
    useTermSearch: () => ({
      data: mocks.searchData,
      isPending: false,
      isError: false,
    }),
  };
});

import { TermTree } from './TermTree';

afterEach(() => {
  cleanup();
  mocks.searchData = [];
  mocks.termsData = [];
});

/** Builds one live term. */
function term(termPath: string, termId = `id-${termPath}`, status = 'draft'): TermSummary {
  return {
    term_id: termId,
    domain_id: 'd1',
    parent_id: null,
    path: termPath,
    name: termPath.split('/').at(-1) ?? termPath,
    definition: 'definition',
    status,
    color: '',
  };
}

/** Builds one keyword hit. */
function hit(termPath: string): TermSearchResult {
  return {
    domain_id: 'd1',
    domain_name: 'Business',
    term_id: `id-${termPath}`,
    term_path: termPath,
    term_name: termPath.split('/').at(-1) ?? termPath,
    definition: 'definition',
    status: 'draft',
    matched_alias: null,
    color: '',
  };
}

describe('TermTree', () => {
  it('loads the terms of a domain only when the domain is expanded', async () => {
    mocks.termsData = [term('Revenue'), term('Revenue/ARR')];
    render(<TermTree onPick={vi.fn()} />);

    expect(screen.getByRole('button', { name: 'Business' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Revenue' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Expand Business' }));

    expect(screen.getByRole('button', { name: 'Revenue' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'ARR' })).toBeInTheDocument();
  });

  it('reports the picked term with its domain and path', async () => {
    const onPick = vi.fn();
    mocks.termsData = [term('Revenue'), term('Revenue/ARR')];
    render(<TermTree onPick={onPick} />);
    await userEvent.click(screen.getByRole('button', { name: 'Expand Business' }));

    await userEvent.click(screen.getByRole('button', { name: 'ARR' }));

    expect(onPick).toHaveBeenCalledWith({
      domainId: 'd1',
      domainName: 'Business',
      termId: 'id-Revenue/ARR',
      name: 'ARR',
      path: 'Revenue/ARR',
    });
  });

  it('keeps the hierarchy of the search hits', async () => {
    mocks.searchData = [hit('Revenue/ARR')];
    render(<TermTree onPick={vi.fn()} />);

    await userEvent.type(screen.getByRole('searchbox', { name: 'Search terms' }), 'arr');

    expect(await screen.findByRole('button', { name: 'Revenue' })).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'ARR' })).toBeInTheDocument();
  });

  it('does not pick a term that is not a draft', async () => {
    const onPick = vi.fn();
    mocks.termsData = [term('ARR', 'id-arr', 'approved')];
    render(<TermTree onPick={onPick} />);
    await userEvent.click(screen.getByRole('button', { name: 'Expand Business' }));

    await userEvent.click(screen.getByRole('button', { name: 'ARR' }));

    expect(onPick).not.toHaveBeenCalled();
  });
});
