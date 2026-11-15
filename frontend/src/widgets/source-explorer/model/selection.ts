/** One source table the user selected for an import. */
export interface SourceTableSelection {
  catalog: string;
  schema: string;
  table: string;
}

/**
 * Builds the stable key of a selected table.
 *
 * @param row Selection row.
 * @returns The key used in the selection set.
 */
export function tableKey(row: SourceTableSelection): string {
  return `${row.catalog}\u0000${row.schema}\u0000${row.table}`;
}
