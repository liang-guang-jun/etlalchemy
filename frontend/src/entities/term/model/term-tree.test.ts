import { describe, expect, it } from 'vitest';

import type { TermSearchResult, TermSummary } from '../api';
import {
  buildTermTree,
  flattenTermTree,
  searchSources,
  summarySources,
  termTreeKey,
  type TermTreeSource,
} from './term-tree';

/** Builds one already known term source. */
function source(path: string, termId: string | null = `id-${path}`): TermTreeSource {
  return {
    domainId: 'd1',
    domainName: 'Business',
    termId,
    path,
    status: 'draft',
    hit: null,
  };
}

/** Builds one keyword hit. */
function hit(termPath: string, termId = `id-${termPath}`): TermSearchResult {
  return {
    domain_id: 'd1',
    domain_name: 'Revenue',
    term_id: termId,
    term_path: termPath,
    term_name: termPath.split('/').at(-1) ?? termPath,
    definition: 'definition',
    status: 'draft',
    matched_alias: null,
    color: '',
  };
}

/** Builds one live term summary. */
function summary(termPath: string, termId = `id-${termPath}`): TermSummary {
  return {
    term_id: termId,
    domain_id: 'd1',
    parent_id: null,
    path: termPath,
    name: termPath.split('/').at(-1) ?? termPath,
    definition: 'definition',
    status: 'draft',
    color: '',
  };
}

describe('termTreeKey', () => {
  it('keys a root row by its domain and a term row by its path', () => {
    expect(termTreeKey('d1', '')).toBe('domain:d1');
    expect(termTreeKey('d1', 'ARR')).toBe('term:d1:ARR');
  });
});

describe('buildTermTree', () => {
  it('nests every term below its parent', () => {
    const [root] = buildTermTree([source('Revenue'), source('Revenue/ARR')]);

    expect(root?.label).toBe('Business');
    expect(root?.children.map((node) => node.label)).toEqual(['Revenue']);
    expect(root?.children[0]?.children[0]?.label).toBe('ARR');
    expect(root?.children[0]?.children[0]?.depth).toBe(2);
  });

  it('adds a placeholder for a path the search did not return', () => {
    const [root] = buildTermTree([source('Revenue/ARR')]);
    const placeholder = root?.children[0];

    expect(placeholder).toMatchObject({ label: 'Revenue', termId: null, path: 'Revenue' });
    expect(placeholder?.children[0]).toMatchObject({ label: 'ARR', termId: 'id-Revenue/ARR' });
  });

  it('promotes a placeholder when the ancestor itself is a source', () => {
    const [root] = buildTermTree([source('Revenue/ARR'), source('Revenue', 'parent')]);

    expect(root?.children).toHaveLength(1);
    expect(root?.children[0]).toMatchObject({ label: 'Revenue', termId: 'parent' });
  });

  it('keeps one root per domain and sorts the labels', () => {
    const roots = buildTermTree([
      { ...source('Zeta'), domainId: 'd2', domainName: 'Sales' },
      source('Balance'),
    ]);

    expect(roots.map((node) => node.label)).toEqual(['Business', 'Sales']);
  });
});

describe('flattenTermTree', () => {
  const tree = buildTermTree([source('Revenue'), source('Revenue/ARR')]);

  it('returns every row when nothing is collapsed', () => {
    expect(flattenTermTree(tree, new Set()).map((row) => row.label)).toEqual([
      'Business',
      'Revenue',
      'ARR',
    ]);
  });

  it('hides the children of a collapsed row', () => {
    const key = termTreeKey('d1', 'Revenue');

    expect(flattenTermTree(tree, new Set([key])).map((row) => row.label)).toEqual([
      'Business',
      'Revenue',
    ]);
  });
});

describe('searchSources', () => {
  it('carries the domain and the hit of every match', () => {
    const [row] = searchSources([hit('Revenue/ARR')]);

    expect(row).toMatchObject({
      domainId: 'd1',
      domainName: 'Revenue',
      termId: 'id-Revenue/ARR',
      path: 'Revenue/ARR',
      status: 'draft',
    });
    expect(row?.hit?.matched_alias).toBeNull();
  });
});

describe('summarySources', () => {
  it('turns the terms of one domain into sources', () => {
    const rows = summarySources({ domain_id: 'd1', name: 'Revenue' }, [summary('ARR')]);

    expect(rows).toEqual([
      {
        domainId: 'd1',
        domainName: 'Revenue',
        termId: 'id-ARR',
        path: 'ARR',
        status: 'draft',
        hit: null,
      },
    ]);
  });
});
