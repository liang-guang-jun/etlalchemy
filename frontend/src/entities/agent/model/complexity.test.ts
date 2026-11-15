import { describe, expect, it } from 'vitest';

import { hasRichContent } from './complexity';

describe('hasRichContent', () => {
  it('flags fenced code blocks', () => {
    expect(hasRichContent('Result:\n\n```sql\nselect 1;\n```')).toBe(true);
  });

  it('flags GitHub tables', () => {
    expect(hasRichContent('| field | type |\n| --- | --- |\n| id | uuid |')).toBe(true);
  });

  it('accepts prose, inline code and lists', () => {
    expect(hasRichContent('Use `catalog_list_tables` and then\n\n- step one\n- step two')).toBe(
      false,
    );
  });
});
