import { afterEach, describe, expect, it, vi } from 'vitest';

import { formatDateTime, formatRelative } from './date';
import { parseTimestamp } from './timestamp';

describe('parseTimestamp', () => {
  it('reads a value without a zone as UTC', () => {
    // SQLite drops the timezone, so the string carries UTC wall time only.
    expect(parseTimestamp('2026-11-15T05:39:00')?.toISOString()).toBe('2026-11-15T05:39:00.000Z');
  });

  it('keeps an explicit zone', () => {
    expect(parseTimestamp('2026-11-15T05:39:00Z')?.toISOString()).toBe('2026-11-15T05:39:00.000Z');
    expect(parseTimestamp('2026-11-15T13:39:00+08:00')?.toISOString()).toBe(
      '2026-11-15T05:39:00.000Z',
    );
  });

  it('accepts the space separator SQLite writes', () => {
    expect(parseTimestamp('2026-11-15 05:39:00')?.toISOString()).toBe('2026-11-15T05:39:00.000Z');
  });

  it('leaves a bare date alone and rejects junk', () => {
    expect(parseTimestamp('2026-11-15')).not.toBeNull();
    expect(parseTimestamp('not a date')).toBeNull();
    expect(parseTimestamp('')).toBeNull();
    expect(parseTimestamp(null)).toBeNull();
  });
});

describe('date formatting', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('reads a zone-less API timestamp as UTC when stating the age', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-11-15T05:40:00Z'));

    // One minute earlier in UTC, written without a zone by SQLite.
    expect(formatRelative('2026-11-15T05:39:00')).toBe('1 min ago');
  });

  it('falls back to the absolute date for missing values', () => {
    expect(formatRelative(null)).toBe('—');
    expect(formatDateTime(undefined)).toBe('—');
  });
});
