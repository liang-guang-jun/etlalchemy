/**
 * Matches a timestamp that already names its zone: `Z` or an offset.
 *
 * The API serialises SQLite rows without an offset because the column drops the
 * timezone, while PostgreSQL keeps it, so both shapes reach the browser.
 */
const WITH_ZONE = /(?:Z|[+-]\d{2}:?\d{2})$/i;

/** Matches a bare calendar date, which has no time of day to shift. */
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Parses an API timestamp.
 *
 * A value without a zone is read as UTC: every writer in the backend stores
 * UTC, and `new Date` would otherwise read it as local time, which shows a
 * wrong "8 hours ago" on any machine east of Greenwich.
 *
 * @param value ISO timestamp, with or without a zone.
 * @returns The parsed moment, or `null` when the value is absent or invalid.
 */
export function parseTimestamp(value: string | null | undefined): Date | null {
  if (value === null || value === undefined) {
    return null;
  }
  const trimmed = value.trim();
  if (trimmed === '') {
    return null;
  }
  const normalized = DATE_ONLY.test(trimmed)
    ? trimmed
    : `${trimmed.replace(' ', 'T')}${WITH_ZONE.test(trimmed) ? '' : 'Z'}`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}
