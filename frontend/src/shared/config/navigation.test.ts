import { describe, expect, it } from 'vitest';

import { describeLocationContext, formatLocationContext, locationContextNote } from './navigation';

describe('describeLocationContext', () => {
  it('names the section and the object chain of a table page', () => {
    const context = describeLocationContext('/catalog/c1/schemas/sales/tables/contacts');

    expect(context.section).toBe('Data catalog');
    expect(context.resources).toEqual([
      { kind: 'catalog', name: 'c1' },
      { kind: 'schema', name: 'sales' },
      { kind: 'table', name: 'contacts' },
    ]);
    expect(context.path).toBe('/catalog/c1/schemas/sales/tables/contacts');
  });

  it('keeps the query string on the path', () => {
    const context = describeLocationContext('/semantic/m1', '?entity=orders');

    expect(context.resources).toEqual([{ kind: 'semantic model', name: 'm1' }]);
    expect(context.path).toBe('/semantic/m1?entity=orders');
  });

  it('reports a section without resources for a list page', () => {
    const context = describeLocationContext('/vocabulary');

    expect(context.section).toBe('Business terms');
    expect(context.resources).toEqual([]);
    expect(formatLocationContext(context)).toBe('Business terms');
  });

  it('returns nothing for a path outside the navigation', () => {
    const context = describeLocationContext('/error');

    expect(context.section).toBeNull();
    expect(formatLocationContext(context)).toBeNull();
    expect(locationContextNote(context)).toBeNull();
  });
});

describe('locationContextNote', () => {
  it('renders the summary and the path the agent should open', () => {
    const note = locationContextNote(
      describeLocationContext('/catalog/c1/schemas/sales/tables/contacts'),
    );

    expect(note).toBe(
      [
        'Data catalog › catalog c1 › schema sales › table contacts',
        'Path: /catalog/c1/schemas/sales/tables/contacts',
      ].join('\n'),
    );
  });

  it('keeps a page with no id at the section name', () => {
    const note = locationContextNote(describeLocationContext('/ingestion'));

    expect(note).toBe('Data sources\nPath: /ingestion');
  });
});
