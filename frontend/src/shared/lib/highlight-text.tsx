import { Fragment, type ReactNode } from 'react';

/**
 * Marks every occurrence of a search term inside a text.
 *
 * The case of the text is preserved, so the highlighted slice is taken from the
 * original string rather than from the lower-cased one.
 *
 * @param text Text to render.
 * @param term Search term; it is trimmed and matched case-insensitively.
 * @returns The plain text, or its parts with every match wrapped in a `mark`.
 */
export function highlightMatches(text: string, term: string): ReactNode {
  const needle = term.trim().toLowerCase();
  if (needle === '') {
    return text;
  }
  const haystack = text.toLowerCase();
  const parts: ReactNode[] = [];
  let cursor = 0;
  let hit = haystack.indexOf(needle, cursor);
  while (hit !== -1) {
    if (hit > cursor) {
      parts.push(text.slice(cursor, hit));
    }
    parts.push(
      <mark
        key={`${String(hit)}-${needle}`}
        className="rounded-sm bg-brand/35 px-0.5 font-semibold text-text-primary"
      >
        {text.slice(hit, hit + needle.length)}
      </mark>,
    );
    cursor = hit + needle.length;
    hit = haystack.indexOf(needle, cursor);
  }
  if (cursor === 0) {
    return text;
  }
  if (cursor < text.length) {
    parts.push(text.slice(cursor));
  }
  return <Fragment key="highlighted">{parts}</Fragment>;
}
