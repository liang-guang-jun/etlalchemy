import { describe, expect, it } from 'vitest';

import { prettyJson } from './json';

describe('prettyJson', () => {
  it('indents a JSON payload', () => {
    expect(prettyJson('{"a":1}')).toBe('{\n  "a": 1\n}');
  });

  it('keeps a payload that is not JSON', () => {
    expect(prettyJson('…(truncated)')).toBe('…(truncated)');
    expect(prettyJson('')).toBe('');
  });
});
