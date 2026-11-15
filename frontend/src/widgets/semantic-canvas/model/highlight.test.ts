import { describe, expect, it } from 'vitest';

import { fieldsByEntity, orderColumns } from './highlight';

const COLUMNS = [
  { name: 'id', dataType: 'uuid' },
  { name: 'campaign_id', dataType: 'uuid' },
  { name: 'name', dataType: 'text' },
  { name: 'channel', dataType: 'varchar(32)' },
];

describe('orderColumns', () => {
  it('keeps the list untouched without a highlight', () => {
    expect(orderColumns(COLUMNS, [])).toEqual(COLUMNS);
  });

  it('moves the highlighted columns to the front', () => {
    expect(orderColumns(COLUMNS, ['channel', 'campaign_id']).map((column) => column.name)).toEqual([
      'campaign_id',
      'channel',
      'id',
      'name',
    ]);
  });

  it('ignores highlighted names that the card does not show', () => {
    expect(orderColumns(COLUMNS, ['lead_id', 'id']).map((column) => column.name)).toEqual([
      'id',
      'campaign_id',
      'name',
      'channel',
    ]);
  });

  it('does not mutate the input', () => {
    const columns = [...COLUMNS];
    orderColumns(columns, ['id']);

    expect(columns.map((column) => column.name)).toEqual(['id', 'campaign_id', 'name', 'channel']);
  });
});

describe('fieldsByEntity', () => {
  it('merges both sides of a relationship', () => {
    const fields = fieldsByEntity([
      { entity: 'Order', field: 'account_id' },
      { entity: 'Account', field: 'account_id' },
    ]);

    expect(fields.get('Order')).toEqual(['account_id']);
    expect(fields.get('Account')).toEqual(['account_id']);
  });

  it('deduplicates repeated references of the same entity', () => {
    const fields = fieldsByEntity([
      { entity: 'Order', field: 'account_id' },
      { entity: 'Order', field: 'account_id' },
      { entity: 'Order', field: 'region_code' },
    ]);

    expect(fields.get('Order')).toEqual(['account_id', 'region_code']);
  });

  it('returns an empty map for no references', () => {
    expect(fieldsByEntity([]).size).toBe(0);
  });
});
