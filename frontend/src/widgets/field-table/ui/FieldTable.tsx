import { useMemo, useState } from 'react';
import { MoreHorizontal, Pencil, Plus, Search } from 'lucide-react';
import { Link } from 'react-router';

import { useFields, type Field } from '@/entities/field';
import { CommentButton } from '@/features/comment-threads';
import {
  AddFieldDialog,
  DiscardFieldConfirm,
  EditFieldDialog,
  RenameFieldDialog,
} from '@/features/field-actions';
import { columnPath } from '@/shared/lib/catalog-routes';
import { Badge, Button, DropdownMenu, ErrorState } from '@/shared/ui';
import { DataTable, type DataTableColumn } from '@/shared/ui';

export interface FieldTableProps {
  catalogId: string;
  schema: string;
  table: string;
}

/**
 * Lists the fields of a table with their row actions.
 *
 * @param props Component props.
 * @returns The field table.
 */
export function FieldTable({ catalogId, schema, table }: FieldTableProps) {
  const { data, isPending, isError, error, refetch } = useFields(catalogId, schema, table);
  const [term, setTerm] = useState('');
  const [addOpen, setAddOpen] = useState(false);
  const [editing, setEditing] = useState<Field | null>(null);
  const [renaming, setRenaming] = useState<Field | null>(null);
  const [discarding, setDiscarding] = useState<Field | null>(null);

  const target = { catalogId, schema, table };

  const columns = useMemo<DataTableColumn<Field>[]>(
    () => [
      {
        key: 'name',
        header: 'Field name',
        render: (row) => (
          <Link
            to={columnPath(catalogId, schema, table, row.name)}
            className="inline-block font-medium text-text-primary transition-transform hover:underline active:scale-95"
          >
            {row.name}
          </Link>
        ),
        sortValue: (row) => row.name,
      },
      {
        key: 'data_type',
        header: 'Type',
        render: (row) => <Badge tone="neutral">{row.data_type}</Badge>,
        sortValue: (row) => row.data_type,
      },
      {
        key: 'nullable',
        header: 'Nullable',
        render: (row) => (row.nullable ? 'Yes' : 'No'),
        sortValue: (row) => (row.nullable ? 1 : 0),
      },
      {
        key: 'actions',
        header: 'Actions',
        render: (row) => (
          <div className="flex translate-x-1 items-center justify-end gap-1 opacity-0 transition-all duration-200 group-hover/row:translate-x-0 group-hover/row:opacity-100 group-focus-within/row:translate-x-0 group-focus-within/row:opacity-100">
            <CommentButton
              target={{
                type: 'field',
                id: row.field_id,
                label: row.name,
                href: columnPath(catalogId, schema, table, row.name),
              }}
            />
            <Button
              size="sm"
              variant="ghost"
              icon={<Pencil className="size-3.5" />}
              onClick={() => {
                setEditing(row);
              }}
            >
              Edit
            </Button>
            <DropdownMenu
              iconOnly
              label={`More actions for ${row.name}`}
              icon={<MoreHorizontal className="size-3.5" aria-hidden="true" />}
              items={[
                {
                  label: 'Rename',
                  onSelect: () => {
                    setRenaming(row);
                  },
                },
                {
                  label: 'Delete',
                  danger: true,
                  onSelect: () => {
                    setDiscarding(row);
                  },
                },
              ]}
            />
          </div>
        ),
      },
    ],
    [catalogId, schema, table],
  );

  const rows = useMemo(() => {
    const all = data ?? [];
    const query = term.trim().toLowerCase();
    if (query === '') {
      return all;
    }
    return all.filter(
      (field) =>
        field.name.toLowerCase().includes(query) || field.data_type.toLowerCase().includes(query),
    );
  }, [data, term]);

  if (isError) {
    return (
      <ErrorState
        detail={error instanceof Error ? error.message : undefined}
        onRetry={() => {
          void refetch();
        }}
      />
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="relative">
          <Search
            className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-text-secondary"
            aria-hidden="true"
          />
          <input
            type="search"
            aria-label="Search fields"
            placeholder="Search fields…"
            value={term}
            onChange={(event) => {
              setTerm(event.target.value);
            }}
            className="h-8 w-64 rounded-md border border-border-strong bg-bg-canvas pl-7 pr-2 text-sm text-text-primary outline-none transition-colors placeholder:text-text-disabled focus:border-brand"
          />
        </div>
        <Button
          size="sm"
          icon={<Plus className="size-4" />}
          onClick={() => {
            setAddOpen(true);
          }}
        >
          Add field
        </Button>
      </div>

      <DataTable
        rows={rows}
        columns={columns}
        getRowId={(row) => row.name}
        loading={isPending}
        emptyTitle={term.trim() === '' ? 'No fields' : 'No matching fields'}
        emptyDescription={
          term.trim() === ''
            ? 'Add the first field to this table.'
            : 'Try another name or data type.'
        }
      />

      <AddFieldDialog open={addOpen} target={target} onClose={() => setAddOpen(false)} />

      {editing !== null ? (
        <EditFieldDialog open target={target} field={editing} onClose={() => setEditing(null)} />
      ) : null}

      {renaming !== null ? (
        <RenameFieldDialog
          open
          target={target}
          field={renaming}
          onClose={() => setRenaming(null)}
        />
      ) : null}

      {discarding !== null ? (
        <DiscardFieldConfirm
          open
          target={target}
          field={discarding}
          onClose={() => setDiscarding(null)}
        />
      ) : null}
    </div>
  );
}
