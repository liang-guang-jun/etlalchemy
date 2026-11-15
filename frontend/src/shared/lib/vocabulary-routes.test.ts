import { describe, expect, it } from 'vitest';

import { domainPath, parseVocabularyPath, termPath } from './vocabulary-routes';

describe('vocabulary routes', () => {
  it('builds a domain path', () => {
    expect(domainPath('abc-123')).toBe('/vocabulary/abc-123');
  });

  it('builds a term path', () => {
    expect(termPath('abc-123', 'term-9')).toBe('/vocabulary/abc-123/terms/term-9');
  });

  it('parses the workspace root', () => {
    expect(parseVocabularyPath('/vocabulary')).toEqual({});
  });

  it('parses a domain route', () => {
    expect(parseVocabularyPath('/vocabulary/abc-123')).toEqual({ domainId: 'abc-123' });
  });

  it('parses a term route', () => {
    expect(parseVocabularyPath('/vocabulary/abc-123/terms/term-9')).toEqual({
      domainId: 'abc-123',
      termId: 'term-9',
    });
  });

  it('returns an empty location for other sections', () => {
    expect(parseVocabularyPath('/catalog/abc-123')).toEqual({});
  });
});
