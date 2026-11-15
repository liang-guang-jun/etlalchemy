import { parseTimestamp } from './timestamp';

const dateTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

/**
 * Formats an ISO timestamp for display.
 *
 * @param value ISO string, or `null` when the value is absent.
 * @returns The formatted timestamp, or `—` for an absent value.
 */
export function formatDateTime(value: string | null | undefined): string {
  const date = parseTimestamp(value);
  if (date === null) {
    return '—';
  }
  return dateTimeFormatter.format(date);
}

/**
 * Formats an ISO timestamp relative to now.
 *
 * @param value ISO string, or `null` when the value is absent.
 * @returns `just now`, `n min ago`, `n h ago`, `n d ago` or the absolute date.
 */
export function formatRelative(value: string | null | undefined): string {
  const date = parseTimestamp(value);
  if (date === null) {
    return '—';
  }
  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  const absolute = Math.abs(seconds);
  if (absolute < 60) {
    return 'just now';
  }
  if (absolute < 3600) {
    return seconds < 0
      ? `${Math.round(absolute / 60)} min ago`
      : `in ${Math.round(absolute / 60)} min`;
  }
  if (absolute < 86_400) {
    return seconds < 0
      ? `${Math.round(absolute / 3600)} h ago`
      : `in ${Math.round(absolute / 3600)} h`;
  }
  if (absolute < 2_592_000) {
    return seconds < 0
      ? `${Math.round(absolute / 86_400)} d ago`
      : `in ${Math.round(absolute / 86_400)} d`;
  }
  return formatDateTime(value);
}
