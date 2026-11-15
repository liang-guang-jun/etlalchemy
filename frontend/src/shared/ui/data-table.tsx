import { useState, type ReactNode } from 'react';
import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table';

import { cn } from '@/shared/lib/cn';
import { EmptyState } from './empty-state';
import { Skeleton } from './skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeaderCell, TableRow } from './table';

export interface DataTableColumn<T> {
  /** Stable identifier of the column. */
  key: string;
  /** Header label. */
  header: string;
  /** Cell renderer. */
  render: (row: T) => ReactNode;
  /** Value used for sorting; the column is not sortable when omitted. */
  sortValue?: (row: T) => string | number;
  /** Extra classes applied to the header and the cells. */
  className?: string;
}

export interface DataTableProps<T> {
  rows: T[];
  columns: DataTableColumn<T>[];
  getRowId: (row: T) => string;
  loading?: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
  /** Optional call to action rendered inside the empty state. */
  emptyAction?: ReactNode;
}

/**
 * Renders a sortable table on top of TanStack Table.
 *
 * @param props Component props.
 * @returns The table element.
 */
export function DataTable<T>({
  rows,
  columns,
  getRowId,
  loading = false,
  emptyTitle = 'No data',
  emptyDescription,
  emptyAction,
}: DataTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>([]);

  const columnDefs: ColumnDef<T>[] = columns.map((column) => ({
    id: column.key,
    accessorFn: column.sortValue ?? (() => ''),
    header: () => column.header,
    cell: (info) => column.render(info.row.original),
    enableSorting: column.sortValue !== undefined,
    enableGlobalFilter: false,
  }));

  const classByKey = new Map(columns.map((column) => [column.key, column.className]));

  const table = useReactTable({
    data: rows,
    columns: columnDefs,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId,
  });

  if (loading) {
    return <Skeleton lines={5} />;
  }

  if (rows.length === 0) {
    return (
      <EmptyState plain title={emptyTitle} description={emptyDescription} action={emptyAction} />
    );
  }

  return (
    <Table>
      <TableHead>
        {table.getHeaderGroups().map((headerGroup) => (
          <tr key={headerGroup.id}>
            {headerGroup.headers.map((header) => (
              <TableHeaderCell key={header.id} className={classByKey.get(header.column.id)}>
                {header.column.getCanSort() ? (
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 hover:text-text"
                    onClick={header.column.getToggleSortingHandler()}
                  >
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    <span
                      aria-hidden="true"
                      className={cn('text-[10px]', !header.column.getIsSorted() && 'opacity-40')}
                    >
                      {header.column.getIsSorted() === 'desc' ? '▼' : '▲'}
                    </span>
                  </button>
                ) : (
                  flexRender(header.column.columnDef.header, header.getContext())
                )}
              </TableHeaderCell>
            ))}
          </tr>
        ))}
      </TableHead>
      <TableBody>
        {table.getRowModel().rows.map((row) => (
          <TableRow key={row.id}>
            {row.getVisibleCells().map((cell) => (
              <TableCell key={cell.id} className={classByKey.get(cell.column.id)}>
                {flexRender(cell.column.columnDef.cell, cell.getContext())}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
