import { describe, expect, it } from 'vitest';

import type { CatalogObjectSearchResult } from '../api';
import {
  columnsByTable,
  countTables,
  filterCatalogTree,
  joinPath,
  objectKey,
  type TreeCatalog,
} from './object-tree';

const TREE: TreeCatalog[] = [
  {
    id: 'c1',
    name: 'Customer 360',
    schemas: [
      {
        id: 's1',
        name: 'service',
        tables: [
          { id: 't1', name: 'dim_segments' },
          { id: 't2', name: 'fct_tickets' },
        ],
      },
    ],
  },
  {
    id: 'c2',
    name: 'Marketing Performance',
    schemas: [
      {
        id: 's2',
        name: 'adtech',
        tables: [
          { id: 't3', name: 'ad_spend' },
          { id: 't4', name: 'leads' },
        ],
      },
    ],
  },
];

const hit = (
  tableId: string,
  fieldName: string,
  extra: Partial<CatalogObjectSearchResult> = {},
): CatalogObjectSearchResult => ({
  kind: 'field',
  target_id: tableId,
  field_name: fieldName,
  name: fieldName,
  path: `x/y/z/${fieldName}`,
  data_type: 'string',
  ...extra,
});

describe('filterCatalogTree', () => {
  it('returns the whole tree for an empty term', () => {
    expect(filterCatalogTree(TREE, '   ')).toHaveLength(2);
  });

  it('keeps the ancestors of a matching table', () => {
    const filtered = filterCatalogTree(TREE, 'dim');

    expect(filtered).toHaveLength(1);
    expect(filtered[0]?.name).toBe('Customer 360');
    expect(filtered[0]?.schemas[0]?.name).toBe('service');
    expect(filtered[0]?.schemas[0]?.tables.map((table) => table.name)).toEqual(['dim_segments']);
  });

  it('drops the siblings that do not match', () => {
    const filtered = filterCatalogTree(TREE, 'lead');
    const tables = filtered.flatMap((catalog) =>
      catalog.schemas.flatMap((schema) => schema.tables.map((table) => table.name)),
    );

    expect(tables).toEqual(['leads']);
  });

  it('keeps a matching schema even without a matching table', () => {
    const filtered = filterCatalogTree(TREE, 'service');

    expect(filtered).toHaveLength(1);
    expect(filtered[0]?.schemas).toHaveLength(1);
    expect(filtered[0]?.schemas[0]?.tables).toHaveLength(0);
  });

  it('keeps a matching catalog without matching children', () => {
    const filtered = filterCatalogTree(TREE, 'marketing');

    expect(filtered.map((catalog) => catalog.name)).toEqual(['Marketing Performance']);
  });

  it('keeps a table whose column matched, and its whole path', () => {
    const filtered = filterCatalogTree(
      TREE,
      'segment_id',
      columnsByTable([hit('t1', 'segment_id')]),
    );

    expect(filtered).toHaveLength(1);
    expect(filtered[0]?.name).toBe('Customer 360');
    expect(filtered[0]?.schemas[0]?.tables.map((table) => table.id)).toEqual(['t1']);
  });

  it('matches case-insensitively', () => {
    expect(countTables(filterCatalogTree(TREE, 'AD_SPEND'))).toBe(1);
  });

  it('returns nothing when no node matches', () => {
    expect(filterCatalogTree(TREE, 'zzz')).toEqual([]);
  });

  it('does not mutate the input tree', () => {
    filterCatalogTree(TREE, 'dim');

    expect(TREE[0]?.schemas[0]?.tables).toHaveLength(2);
  });
});

describe('columnsByTable', () => {
  it('groups the field hits by their owning table', () => {
    const hits = columnsByTable([
      hit('t1', 'segment_id'),
      hit('t1', 'segment_name', { data_type: 'varchar' }),
      hit('t4', 'leads_channel'),
      // Non-field hits belong to the upper levels, which the tree already knows.
      { ...hit('t2', ''), kind: 'table', field_name: '', name: 'fct_tickets' },
    ]);

    expect([...hits.keys()]).toEqual(['t1', 't4']);
    expect(hits.get('t1')).toEqual([
      { name: 'segment_id', data_type: 'string' },
      { name: 'segment_name', data_type: 'varchar' },
    ]);
  });

  it('does not repeat a column reported twice', () => {
    const hits = columnsByTable([hit('t1', 'segment_id'), hit('t1', 'segment_id')]);

    expect(hits.get('t1')).toHaveLength(1);
  });
});

describe('countTables', () => {
  it('counts the tables of the filtered tree', () => {
    // `ad` sits in `ad_spend` and inside `leads`.
    expect(countTables(filterCatalogTree(TREE, 'ad'))).toBe(2);
    expect(countTables(filterCatalogTree(TREE, ''))).toBe(4);
  });
});

describe('objectKey', () => {
  it('keeps the levels apart, and adds the column of a field', () => {
    expect(objectKey('catalog', 'x')).toBe('catalog:x');
    expect(objectKey('field', 'x', 'total')).toBe('field:x:total');
  });
});

describe('joinPath', () => {
  it('joins the names of the ancestors', () => {
    expect(joinPath('analytics', 'sales', 'orders')).toBe('analytics / sales / orders');
  });
});
