import { describe, expect, it } from 'vitest';

import { ALL_DIAGRAM, modelPath, parseWorkspaceSearch, workspacePath } from './semantic-routes';

describe('semantic routes', () => {
  it('builds a model path', () => {
    expect(modelPath('abc-123')).toBe('/semantic/abc-123');
  });

  it('builds a plain workspace path without state', () => {
    expect(workspacePath('abc-123')).toBe('/semantic/abc-123');
  });

  it('encodes the diagram and the selection', () => {
    expect(workspacePath('abc-123', { diagram: ALL_DIAGRAM, entity: 'Customer' })).toBe(
      '/semantic/abc-123?diagram=All&entity=Customer',
    );
  });

  it('drops empty state values', () => {
    expect(workspacePath('abc-123', { diagram: '', entity: '' })).toBe('/semantic/abc-123');
  });

  it('parses a workspace query string', () => {
    expect(parseWorkspaceSearch('?diagram=Sales&entity=Order&relationship=r-1')).toEqual({
      diagram: 'Sales',
      entity: 'Order',
      relationship: 'r-1',
    });
  });

  it('parses a query string without the leading question mark', () => {
    expect(parseWorkspaceSearch('diagram=Sales')).toEqual({
      diagram: 'Sales',
      entity: undefined,
      relationship: undefined,
    });
  });

  it('treats an empty query string as no state', () => {
    expect(parseWorkspaceSearch('')).toEqual({
      diagram: undefined,
      entity: undefined,
      relationship: undefined,
    });
  });
});
