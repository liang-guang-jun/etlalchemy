/** How much of an entity card is shown on the canvas. */
export type EntityDetailLevel = 'table' | 'relations' | 'all';

/** Storage key of the chosen detail level. */
const STORAGE_KEY = 'semantic:entityDetailLevel';

/** The three levels, in the order the switch renders them. */
export const ENTITY_DETAIL_LEVELS: {
  value: EntityDetailLevel;
  label: string;
  hint: string;
}[] = [
  {
    value: 'table',
    label: 'Table',
    hint: 'Show only the entity and its catalog table',
  },
  {
    value: 'relations',
    label: 'Relations',
    hint: 'Also show the columns that relationships use',
  },
  {
    value: 'all',
    label: 'All columns',
    hint: 'Show every column of the catalog table',
  },
];

/**
 * Reads the detail level this browser used last.
 *
 * @returns The stored level, `table` when nothing is stored.
 */
export function readDetailLevel(): EntityDetailLevel {
  const value = window.localStorage.getItem(STORAGE_KEY);
  return value === 'relations' || value === 'all' ? value : 'table';
}

/**
 * Remembers the detail level for the next visit.
 *
 * @param level Level to store.
 */
export function writeDetailLevel(level: EntityDetailLevel): void {
  window.localStorage.setItem(STORAGE_KEY, level);
}
