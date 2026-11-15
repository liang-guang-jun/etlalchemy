const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Checks whether a value is a UUID, so a path segment can be addressed by name
 * or by id.
 *
 * @param value Candidate path segment.
 * @returns `true` when the value is a UUID.
 */
export function isUuid(value: string): boolean {
  return UUID_PATTERN.test(value);
}
