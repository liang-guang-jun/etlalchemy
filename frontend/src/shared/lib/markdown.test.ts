import { describe, expect, it } from 'vitest';

import { markdownToText } from './markdown';

describe('markdownToText', () => {
  it('drops emphasis, heading and list markers', () => {
    expect(markdownToText('**ARR** from\n\n- seats\n- commitment')).toBe(
      'ARR from seats commitment',
    );
  });

  it('keeps link labels and strips fences', () => {
    expect(markdownToText('See [the contract](https://x.test).\n\n```sql\nselect 1\n```')).toBe(
      'See the contract.',
    );
  });

  it('returns an empty string for empty input', () => {
    expect(markdownToText('   \n  ')).toBe('');
  });
});
