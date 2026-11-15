/** Path of a vocabulary domain page. */
export function domainPath(domainId: string): string {
  return `/vocabulary/${encodeURIComponent(domainId)}`;
}

/** Path of a term inside a domain. */
export function termPath(domainId: string, termId: string): string {
  return `${domainPath(domainId)}/terms/${encodeURIComponent(termId)}`;
}

/** Location segments addressed by a vocabulary URL. */
export interface VocabularyLocation {
  domainId?: string;
  termId?: string;
}

/**
 * Reads the domain and term segments of a pathname.
 *
 * @param pathname Current router pathname.
 * @returns The decoded segments, with the missing ones left `undefined`.
 */
export function parseVocabularyPath(pathname: string): VocabularyLocation {
  const segments = pathname.split('/').filter((segment) => segment !== '');
  if (segments[0] !== 'vocabulary') {
    return {};
  }
  const decode = (value: string | undefined) =>
    value === undefined ? undefined : decodeURIComponent(value);

  return {
    domainId: decode(segments[1]),
    // Terms are addressed by id only: a term path contains slashes.
    termId: segments[2] === 'terms' ? decode(segments[3]) : undefined,
  };
}
