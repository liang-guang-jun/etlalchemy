import { useMemo, useState } from 'react';
import { Boxes, Database, KeyRound, Link2, ListChecks, Plus } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { Link, useNavigate } from 'react-router';

import { useConnections, useImportRuns, type Connection } from '@/entities/ingestion';
import { CreateConnectionDialog } from '@/features/connection-actions';
import { connectionPath } from '@/shared/lib/ingestion-routes';
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  PageHeader,
  SearchInput,
  Skeleton,
  Tabs,
} from '@/shared/ui';
import { ImportRunTable } from '@/widgets/import-run-table';

type TabValue = 'connections' | 'runs';

/**
 * Formats the credential of a connection without leaking the secret.
 *
 * @param connection Connection row.
 * @returns The credential label.
 */
function credentialLabel(connection: Connection): string {
  if (connection.has_inline_credential) {
    return 'inline token';
  }
  const reference = connection.credential_ref ?? '';
  if (reference.startsWith('profile:')) {
    const profile = reference.slice('profile:'.length);
    return profile === '' ? 'local profile (default)' : `local profile ${profile}`;
  }
  return connection.credential_ref ?? 'no credential';
}

/**
 * Renders the data source workspace: the connection cards and the import runs
 * of the whole server, as two tabs of one page.
 *
 * @returns The data sources page.
 */
export default function IngestionListPage() {
  const navigate = useNavigate();
  const connections = useConnections();
  const [tab, setTab] = useState<TabValue>('connections');
  const runs = useImportRuns(undefined, tab === 'runs');
  const [createOpen, setCreateOpen] = useState(false);
  const [term, setTerm] = useState('');

  const connectionNames = useMemo(
    () => new Map((connections.data ?? []).map((row) => [row.connection_id, row.name])),
    [connections.data],
  );

  const filtered = useMemo(() => {
    const needle = term.trim().toLowerCase();
    const rows = connections.data ?? [];
    if (needle === '') {
      return rows;
    }
    return rows.filter((row) =>
      [row.name, row.kind, row.endpoint, row.default_catalog ?? ''].some((value) =>
        value.toLowerCase().includes(needle),
      ),
    );
  }, [connections.data, term]);

  const orderedRuns = useMemo(() => [...(runs.data ?? [])].reverse(), [runs.data]);

  const newConnectionButton = (
    <Button
      icon={<Plus className="size-4" />}
      onClick={() => {
        setCreateOpen(true);
      }}
    >
      New connection
    </Button>
  );

  return (
    <div>
      <PageHeader
        title="Data sources"
        description="Connect an external warehouse, copy its metadata into a catalog and follow every import."
        actions={
          tab === 'connections' ? (
            <>
              <SearchInput
                ariaLabel="Search connections"
                placeholder="Search connections…"
                value={term}
                onChange={setTerm}
              />
              {newConnectionButton}
            </>
          ) : undefined
        }
      />

      <Tabs
        className="mb-4"
        items={[
          { value: 'connections', label: 'Connections', count: connections.data?.length },
          { value: 'runs', label: 'Import runs', count: runs.data?.length },
        ]}
        value={tab}
        onChange={(value) => {
          setTab(value === 'runs' ? 'runs' : 'connections');
        }}
      />

      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={tab}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.16, ease: 'easeOut' }}
        >
          {tab === 'runs' ? (
            runs.isPending ? (
              <Skeleton lines={6} />
            ) : runs.isError ? (
              <ErrorState
                detail={runs.error instanceof Error ? runs.error.message : undefined}
                onRetry={() => {
                  void runs.refetch();
                }}
              />
            ) : orderedRuns.length === 0 ? (
              <EmptyState
                icon={<ListChecks className="size-10" aria-hidden="true" />}
                title="No import has run yet"
                description="Open a data source and start an import to see it here."
                action={
                  <Button
                    variant="secondary"
                    onClick={() => {
                      setTab('connections');
                    }}
                  >
                    Browse data sources
                  </Button>
                }
                className="py-20"
              />
            ) : (
              <ImportRunTable runs={orderedRuns} connectionNames={connectionNames} showConnection />
            )
          ) : connections.isPending ? (
            <Skeleton lines={6} />
          ) : connections.isError ? (
            <ErrorState
              detail={connections.error instanceof Error ? connections.error.message : undefined}
              onRetry={() => {
                void connections.refetch();
              }}
            />
          ) : (connections.data ?? []).length === 0 ? (
            <EmptyState
              icon={<Boxes className="size-10" aria-hidden="true" />}
              title="No data sources yet"
              description="Add a connection to a warehouse, then import its catalogs into ETLAlchemy."
              action={newConnectionButton}
              className="py-20"
            />
          ) : filtered.length === 0 ? (
            <EmptyState
              plain
              title="No connection matches"
              description={`Nothing matches “${term}”.`}
            />
          ) : (
            <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {filtered.map((connection) => (
                <motion.li
                  key={connection.connection_id}
                  layout
                  whileHover={{ y: -2 }}
                  transition={{ type: 'spring', stiffness: 420, damping: 28 }}
                  className="group relative flex flex-col gap-3 rounded-lg border border-border-base bg-bg-surface p-4 transition-colors hover:border-border-strong"
                >
                  <Link
                    to={connectionPath(connection.connection_id)}
                    aria-label={`Open ${connection.name}`}
                    className="absolute inset-0 rounded-lg"
                  />
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-brand/15 text-text-primary">
                        <Database className="size-4" aria-hidden="true" />
                      </span>
                      <span className="truncate font-semibold text-text-primary">
                        {connection.name}
                      </span>
                    </div>
                    <Badge tone="info">{connection.kind}</Badge>
                  </div>
                  <p className="truncate font-mono text-xs text-text-secondary">
                    {connection.endpoint}
                  </p>
                  <div className="mt-auto flex flex-wrap items-center gap-3 text-xs text-text-secondary">
                    <span className="inline-flex items-center gap-1">
                      <Link2 className="size-3.5 text-text-disabled" aria-hidden="true" />
                      {connection.default_catalog ?? 'no default catalog'}
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <KeyRound className="size-3.5 text-text-disabled" aria-hidden="true" />
                      {credentialLabel(connection)}
                    </span>
                  </div>
                </motion.li>
              ))}
            </ul>
          )}
        </motion.div>
      </AnimatePresence>

      <CreateConnectionDialog
        open={createOpen}
        onClose={() => {
          setCreateOpen(false);
        }}
        onCreated={(connectionId) => {
          void navigate(connectionPath(connectionId));
        }}
      />
    </div>
  );
}
