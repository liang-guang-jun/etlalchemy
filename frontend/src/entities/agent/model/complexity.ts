/**
 * Detects markdown that needs the width of the full page.
 *
 * The floating widget renders a narrow column, where a table or a fenced code
 * block would only show a horizontal scrollbar; it points at the full page
 * instead of squeezing the content.
 *
 * @param source Markdown source.
 * @returns `true` when the source holds a table or a fenced code block.
 */
export function hasRichContent(source: string): boolean {
  if (/^\s*(```|~~~)/m.test(source)) {
    return true;
  }
  // A GitHub table needs a delimiter row such as `| --- | --- |`.
  return /^\s*\|?[\s:-]*-[\s:|-]*\|/m.test(source);
}
