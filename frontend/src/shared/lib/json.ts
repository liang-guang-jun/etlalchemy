/**
 * Renders a JSON payload for a read-only detail panel.
 *
 * @param text Compact JSON, or text that is not JSON at all.
 * @returns Indented JSON, or the original text when it cannot be parsed.
 */
export function prettyJson(text: string): string {
  if (text === '') {
    return '';
  }
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}
