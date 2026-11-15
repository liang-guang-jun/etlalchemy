import type { ImportRun } from '@/entities/ingestion';
import { Badge, Dialog } from '@/shared/ui';

export interface RunDetailsDialogProps {
  run: ImportRun | null;
  connectionName?: string;
  catalogName?: string;
  onClose: () => void;
}

interface DetailRowProps {
  label: string;
  value: string;
}

/**
 * Renders one label/value pair of the run summary.
 *
 * @param props Component props.
 * @returns The row element.
 */
function DetailRow({ label, value }: DetailRowProps) {
  return (
    <div className="grid grid-cols-3 gap-3 py-1.5">
      <span className="text-sm text-text-secondary">{label}</span>
      <span className="col-span-2 font-mono text-xs break-all text-text-primary">{value}</span>
    </div>
  );
}

/**
 * Renders the full record of one import run.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function RunDetailsDialog({
  run,
  connectionName,
  catalogName,
  onClose,
}: RunDetailsDialogProps) {
  const selected = Object.entries(run?.include_tables ?? {});
  const mapping = Object.entries(run?.schema_mapping ?? {});

  return (
    <Dialog open={run !== null} title="Import run" size="lg" onClose={onClose}>
      {run === null ? null : (
        <div className="divide-y divide-border-base">
          <div>
            <DetailRow label="Run" value={run.run_id} />
            <DetailRow label="Status" value={run.status} />
            <DetailRow label="Started" value={new Date(run.created_at).toLocaleString()} />
            {connectionName === undefined ? null : (
              <DetailRow label="Connection" value={connectionName} />
            )}
            <DetailRow label="Target catalog" value={catalogName ?? run.target_catalog_id} />
            <DetailRow label="Source catalog" value={run.source_catalog ?? 'all catalogs'} />
            <DetailRow
              label="Counts"
              value={`${run.schema_count} schemas · ${run.table_count} tables · ${run.field_count} fields`}
            />
          </div>

          <div className="py-2">
            <p className="mb-1 text-sm text-text-secondary">Selection</p>
            {selected.length === 0 ? (
              <p className="text-sm text-text-disabled">The whole source catalog was imported.</p>
            ) : (
              <ul className="space-y-1">
                {selected.map(([schema, tables]) => (
                  <li key={schema} className="text-sm text-text-primary">
                    <span className="font-mono text-xs">{schema}</span>
                    <span className="ml-2 text-text-secondary">
                      {tables.join(', ') || 'all tables'}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {mapping.length === 0 ? null : (
              <p className="mt-2 flex flex-wrap gap-1.5">
                {mapping.map(([from, to]) => (
                  <Badge key={from} tone="info">
                    {from} → {to}
                  </Badge>
                ))}
              </p>
            )}
          </div>

          {run.error === null ? null : (
            <div className="py-2">
              <p className="mb-1 text-sm text-text-secondary">Error</p>
              <pre className="overflow-x-auto rounded-sm bg-danger/5 p-2 font-mono text-xs whitespace-pre-wrap text-danger">
                {run.error}
              </pre>
            </div>
          )}
        </div>
      )}
    </Dialog>
  );
}
