import { describe, expect, it } from 'vitest';

import { filterConversations, groupConversations } from './grouping';

/** Reference moment used by every case: 15 Nov 2026, 12:00 local time. */
const NOW = new Date(2026, 10, 15, 12, 0, 0);

/** Builds a conversation stub with the given title and activity. */
function conversation(title: string, activity: Date) {
  return { title, last_activity_at: activity.toISOString() };
}

describe('groupConversations', () => {
  const rows = [
    conversation('today morning', new Date(2026, 10, 15, 9, 0)),
    conversation('today late', new Date(2026, 10, 15, 11, 30)),
    conversation('yesterday evening', new Date(2026, 10, 14, 23, 0)),
    conversation('three days ago', new Date(2026, 10, 12, 8, 0)),
    conversation('last month', new Date(2026, 9, 2, 8, 0)),
  ];

  it('buckets by calendar day and keeps the recent rows first', () => {
    const groups = groupConversations(rows, NOW);

    expect(groups.map((group) => group.label)).toEqual([
      'Today',
      'Yesterday',
      'Previous 7 Days',
      'Older',
    ]);
    expect(groups[0]?.items.map((item) => item.title)).toEqual(['today late', 'today morning']);
    expect(groups[1]?.items.map((item) => item.title)).toEqual(['yesterday evening']);
  });

  it('omits empty buckets', () => {
    const groups = groupConversations(
      [conversation('only today', new Date(2026, 10, 15, 10, 0))],
      NOW,
    );

    expect(groups).toHaveLength(1);
    expect(groups[0]?.label).toBe('Today');
  });

  it('does not mutate the input order', () => {
    const input = [conversation('a', new Date(2026, 10, 15, 8, 0))];
    const snapshot = input.map((item) => item.title);

    groupConversations(input, NOW);

    expect(input.map((item) => item.title)).toEqual(snapshot);
  });
});

describe('filterConversations', () => {
  const rows = [conversation('Revenue analysis', NOW), conversation('Churn export', NOW)];

  it('matches the title case-insensitively', () => {
    expect(filterConversations(rows, 'REVENUE').map((row) => row.title)).toEqual([
      'Revenue analysis',
    ]);
  });

  it('keeps every row for a blank term', () => {
    expect(filterConversations(rows, '  ')).toHaveLength(2);
  });
});
