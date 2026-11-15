/** One column rendered inside an entity card. */
export interface ColumnRow {
  /** Field name. */
  name: string;
  /** Field type, empty when the card only knows the name. */
  dataType: string;
}

/**
 * Moves the columns a highlighted relationship uses to the front.
 *
 * The order of the remaining columns is kept, so the card only ever swaps two
 * groups instead of reshuffling everything, and an empty highlight leaves the
 * list untouched.
 *
 * @param columns Columns as the detail level produced them.
 * @param highlighted Field names of the highlighted relationship.
 * @returns A new list with the highlighted columns first.
 */
export function orderColumns(
  columns: readonly ColumnRow[],
  highlighted: readonly string[],
): ColumnRow[] {
  if (highlighted.length === 0) {
    return [...columns];
  }
  const wanted = new Set(highlighted);
  const used: ColumnRow[] = [];
  const rest: ColumnRow[] = [];
  for (const column of columns) {
    if (wanted.has(column.name)) {
      used.push(column);
    } else {
      rest.push(column);
    }
  }
  return [...used, ...rest];
}

/**
 * Collects the field pairs of a relationship per entity.
 *
 * Both the from and the to side can name the same entity, so the fields are
 * merged without duplicates.
 *
 * @param refs Every `(entity, field)` reference of one relationship.
 * @returns Field names keyed by entity name.
 */
export function fieldsByEntity(
  refs: readonly { entity: string; field: string }[],
): Map<string, string[]> {
  const fields = new Map<string, string[]>();
  for (const ref of refs) {
    const list = fields.get(ref.entity) ?? [];
    if (!list.includes(ref.field)) {
      list.push(ref.field);
    }
    fields.set(ref.entity, list);
  }
  return fields;
}
