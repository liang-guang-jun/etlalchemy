import { Table2, X } from 'lucide-react';

import { CatalogObjectTree } from '@/entities/catalog';
import { useTableLocation } from '@/entities/table';
import { Button } from '@/shared/ui';

/** One catalog table chosen as the backing table of an entity. */
export interface PickedTable {
  id: string;
  /** `catalog / schema / table` path; resolved from the read model when it is missing. */
  label?: string;
}

export interface TablePickerProps {
  value: PickedTable | null;
  onChange: (value: PickedTable | null) => void;
  /** Locks the choice, e.g. because a relationship references the entity. */
  disabled?: boolean;
}

/**
 * Picks the catalog table an entity maps to.
 *
 * The choice is made in the catalog tree the resource explorer of the data
 * catalog shows — catalog → schema → table, searchable, with the ancestors of a
 * hit kept in place — instead of a flat list of search results. Once a table is
 * chosen the tree collapses into a chip that can be changed again.
 *
 * @param props Component props.
 * @returns The picker element.
 */
export function TablePicker({ value, onChange, disabled = false }: TablePickerProps) {
  const location = useTableLocation(value?.id ?? '');
  const table = location.data;

  if (value !== null) {
    const label =
      value.label ??
      (table === undefined
        ? `table ${value.id.slice(0, 8)}…`
        : `${table.schema_name}.${table.name}`);

    return (
      <div className="flex items-center justify-between gap-2 rounded-md border border-border-base bg-bg-canvas px-3 py-2">
        <span className="flex min-w-0 items-center gap-2">
          <Table2 className="size-4 shrink-0 text-text-secondary" aria-hidden="true" />
          <span className="truncate font-mono text-sm text-text-primary">{label}</span>
        </span>
        <Button
          variant="ghost"
          size="sm"
          disabled={disabled}
          onClick={() => {
            onChange(null);
          }}
        >
          <X className="size-3.5" aria-hidden="true" />
          Change
        </Button>
      </div>
    );
  }

  return (
    <CatalogObjectTree
      selectable={['table']}
      onSelect={(object) => {
        onChange({ id: object.targetId, label: object.path });
      }}
    />
  );
}
