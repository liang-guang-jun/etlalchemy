import { useMemo, useState, type ReactNode } from 'react';
import { ExternalLink } from 'lucide-react';
import { Link } from 'react-router';

import { useCatalogs } from '@/entities/catalog';
import type { ImportRun } from '@/entities/ingestion';
import { catalogPath } from '@/shared/lib/catalog-routes';
import { connectionPath } from '@/shared/lib/ingestion-routes';
import { DataTable, type DataTableColumn } from '@/shared/ui';

import { RunDetailsDialog } from './RunDetailsDialog';
import { RunStatusBadge } from './RunStatusBadge';

export interface ImportRunTableProps {
  runs: ImportRun[];
  /** Connection name keyed by connection id, used by the global run list. */
  connectionNames?: Map<string, string>;
  /** Renders the owning connection as its own column. */
  showConnection?: boolean;
  /** Call to action rendered when there is no run yet. */
  emptyAction?: ReactNode;
}

/**
 * Renders the import history of one connection or of the whole server.
 *
 * @param props Component props.
 * @returns The run table with its details dialog.
 */
export function ImportRunTable({
  runs,
  connectionNames,
  showConnection = false,
  emptyAction,
}: ImportRunTableProps) {
  const [selected, setSelected] = useState<ImportRun | null>(null);
  const catalogs = useCatalogs();

  const catalogNames = useMemo(
    () => new Map((catalogs.data ?? []).map((row) => [row.catalog_id, row.name])),
    [catalogs.data],
  );

  const columns = useMemo<DataTableColumn<ImportRun>[]>(() => {
    const base: DataTableColumn<ImportRun>[] = [
      {
        key: 'run',
        header: 'Run',
        sortValue: (row) => row.created_at,
        render: (row) => (
          <span className="font-mono text-xs text-text-secondary">{row.run_id.slice(0, 8)}</span>
        ),
      },
    ];
    if (showConnection) {
      base.push({
        key: 'connection',
        header: 'Connection',
        sortValue: (row) => connectionNames?.get(row.connection_id) ?? row.connection_id,
        render: (row) => (
          <Link
            to={connectionPath(row.connection_id)}
            className="text-text-primary hover:underline"
          >
            {connectionNames?.get(row.connection_id) ?? 'unknown'}
          </Link>
        ),
      });
    }
    base.push(
      {
        key: 'target',
        header: 'Target catalog',
        sortValue: (row) => catalogNames.get(row.target_catalog_id) ?? row.target_catalog_id,
        render: (row) => (
          <Link
            to={catalogPath(row.target_catalog_id)}
            className="inline-flex items-center gap-1 text-text-primary hover:underline"
          >
            {catalogNames.get(row.target_catalog_id) ?? row.target_catalog_id.slice(0, 8)}
            <ExternalLink className="size-3 text-text-disabled" aria-hidden="true" />
          </Link>
        ),
      },
      {
        key: 'status',
        header: 'Status',
        sortValue: (row) => row.status,
        render: (row) => <RunStatusBadge status={row.status} />,
      },
      {
        key: 'counts',
        header: 'Schemas / Tables / Fields',
        sortValue: (row) => row.table_count,
        render: (row) => (
          <span
            className="font-mono text-xs whitespace-nowrap text-text-secondary"
            title={`${row.schema_count} schemas, ${row.table_count} tables, ${row.field_count} fields imported`}
          >
            {row.schema_count} / {row.table_count} / {row.field_count}
          </span>
        ),
      },
      {
        key: 'started',
        header: 'Started',
        sortValue: (row) => row.created_at,
        render: (row) => (
          <span className="text-sm whitespace-nowrap text-text-secondary">
            {new Date(row.created_at).toLocaleString()}
          </span>
        ),
      },
      {
        key: 'actions',
        header: '',
        render: (row) => (
          <button
            type="button"
            className="text-xs text-text-secondary hover:text-text-primary hover:underline"
            onClick={() => {
              setSelected(row);
            }}
          >
            Details
          </button>
        ),
      },
    );
    return base;
  }, [catalogNames, connectionNames, showConnection]);

  return (
    <>
      <DataTable
        rows={runs}
        columns={columns}
        getRowId={(row) => row.run_id}
        emptyTitle="No imports yet"
        emptyDescription="Start an import to copy a source catalog into a target catalog."
        emptyAction={emptyAction}
      />
      <RunDetailsDialog
        run={selected}
        connectionName={
          selected === null ? undefined : connectionNames?.get(selected.connection_id)
        }
        catalogName={selected === null ? undefined : catalogNames.get(selected.target_catalog_id)}
        onClose={() => {
          setSelected(null);
        }}
      />
    </>
  );
}
