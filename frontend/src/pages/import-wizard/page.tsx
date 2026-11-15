import { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, Check, Loader2, Play, Sparkles, TriangleAlert } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { Link, useNavigate, useParams } from 'react-router';

import { useCatalogs } from '@/entities/catalog';
import { useConnection, useImportPlan, type ImportRequest } from '@/entities/ingestion';
import { useStartImport } from '@/features/import-wizard';
import { cn } from '@/shared/lib/cn';
import { connectionPath } from '@/shared/lib/ingestion-routes';
import { Button, EmptyState, ErrorState, Select, Skeleton } from '@/shared/ui';
import {
  ImportSelectionPanel,
  SourceExplorer,
  tableKey,
  type SourceTableSelection,
} from '@/widgets/source-explorer';

const STEPS = [
  { id: 1, label: 'Target' },
  { id: 2, label: 'Select tables' },
  { id: 3, label: 'Confirm' },
] as const;

/** Rotating status texts shown while the synchronous import runs. */
const PROGRESS_MESSAGES = [
  'Connecting to the source…',
  'Scanning the source catalog…',
  'Comparing metadata with the target…',
  'Upserting schemas, tables and fields…',
];

/**
 * Groups the selected tables into the `include_tables` payload.
 *
 * @param selection Selected source tables.
 * @returns Table names keyed by source schema.
 */
function groupTables(selection: SourceTableSelection[]): Record<string, string[]> {
  const grouped: Record<string, string[]> = {};
  for (const row of selection) {
    grouped[row.schema] = [...(grouped[row.schema] ?? []), row.table];
  }
  return grouped;
}

/**
 * Drops identity mappings so the request only carries real renames.
 *
 * @param mapping Target schema name keyed by source schema.
 * @returns The mappings that change something.
 */
function cleanMapping(mapping: Record<string, string>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(mapping)
      .map(([from, to]) => [from, to.trim()])
      .filter(([from, to]) => to !== '' && to !== from),
  );
}

/**
 * Renders the numbered progress rail of the wizard.
 *
 * @param props Component props.
 * @returns The step indicator.
 */
function StepIndicator({ step }: { step: number }) {
  return (
    <ol className="mb-6 flex items-center gap-3">
      {STEPS.map((entry, index) => {
        const done = step > entry.id;
        const active = step === entry.id;
        return (
          <li key={entry.id} className="flex flex-1 items-center gap-2">
            <motion.span
              animate={{
                scale: active ? 1 : 0.9,
                backgroundColor: done || active ? 'var(--color-brand)' : 'var(--color-bg-canvas)',
              }}
              className={cn(
                'flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
                done || active
                  ? 'text-brand-text'
                  : 'border border-border-strong text-text-secondary',
              )}
            >
              {done ? <Check className="size-3.5" aria-hidden="true" /> : entry.id}
            </motion.span>
            <span
              className={cn(
                'text-sm whitespace-nowrap',
                active ? 'font-medium text-text-primary' : 'text-text-secondary',
              )}
            >
              {entry.label}
            </span>
            {index < STEPS.length - 1 ? (
              <span className="h-px flex-1 bg-border-base" aria-hidden="true" />
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

/**
 * Renders the non-blocking panel shown while the import command runs.
 *
 * @param props Component props.
 * @returns The progress panel.
 */
function ProgressPanel({ visible }: { visible: boolean }) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (!visible) {
      return undefined;
    }
    setIndex(0);
    const timer = window.setInterval(() => {
      setIndex((value) => (value + 1) % PROGRESS_MESSAGES.length);
    }, 1_600);
    return () => {
      window.clearInterval(timer);
    };
  }, [visible]);

  return (
    <AnimatePresence>
      {visible ? (
        <motion.div
          initial={{ y: 50, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: 50, opacity: 0 }}
          transition={{ type: 'spring', stiffness: 320, damping: 28 }}
          className="fixed right-6 bottom-6 z-50 flex w-80 items-start gap-3 rounded-lg border border-border-strong bg-bg-surface p-4 shadow-lg"
          role="status"
        >
          <motion.span
            animate={{ rotate: 360 }}
            transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
            className="mt-0.5"
          >
            <Loader2 className="size-4 text-brand" aria-hidden="true" />
          </motion.span>
          <div className="min-w-0">
            <p className="text-sm font-medium text-text-primary">Import running</p>
            <div className="relative h-5 overflow-hidden">
              <AnimatePresence mode="wait" initial={false}>
                <motion.p
                  key={index}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.18 }}
                  className="text-xs text-text-secondary"
                >
                  {PROGRESS_MESSAGES[index]}
                </motion.p>
              </AnimatePresence>
            </div>
            <p className="mt-1 text-[11px] text-text-disabled">
              Keep this tab open; the run is recorded either way.
            </p>
          </div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

/**
 * Renders the three-step import wizard of one connection.
 *
 * @returns The import wizard page.
 */
export default function ImportWizardPage() {
  const { connectionId = '' } = useParams<{ connectionId: string }>();
  const navigate = useNavigate();
  const connection = useConnection(connectionId);
  const catalogs = useCatalogs();
  const startImport = useStartImport(connectionId);
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [targetCatalogId, setTargetCatalogId] = useState('');
  const [sourceCatalog, setSourceCatalog] = useState('');
  const [selection, setSelection] = useState<SourceTableSelection[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({});

  const selectedKeys = useMemo(() => new Set(selection.map(tableKey)), [selection]);
  const body: ImportRequest | null =
    targetCatalogId === ''
      ? null
      : {
          target_catalog_id: targetCatalogId,
          source_catalog: sourceCatalog.trim() === '' ? null : sourceCatalog.trim(),
          include_tables: groupTables(selection),
          schema_mapping: cleanMapping(mapping),
        };
  const plan = useImportPlan(
    connectionId,
    body ?? { target_catalog_id: '' },
    step === 3 && body !== null,
  );

  if (connection.isPending) {
    return <Skeleton lines={6} />;
  }
  if (connection.isError || connection.data === undefined) {
    return (
      <ErrorState
        detail={connection.error instanceof Error ? connection.error.message : undefined}
        onRetry={() => {
          void connection.refetch();
        }}
      />
    );
  }

  const toggleTable = (row: SourceTableSelection) => {
    const key = tableKey(row);
    setSelection((current) =>
      current.some((item) => tableKey(item) === key)
        ? current.filter((item) => tableKey(item) !== key)
        : [...current, row],
    );
  };

  const toggleSchema = (rows: SourceTableSelection[], select: boolean) => {
    setSelection((current) => {
      const keys = new Set(rows.map(tableKey));
      const kept = current.filter((item) => !keys.has(tableKey(item)));
      return select ? [...kept, ...rows] : kept;
    });
  };

  const submit = () => {
    if (body === null) {
      return;
    }
    startImport.mutate(body, {
      onSuccess: () => {
        void navigate(connectionPath(connectionId));
      },
    });
  };

  const catalogOptions = (catalogs.data ?? []).map((row) => ({
    value: row.catalog_id,
    label: row.name,
  }));

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex items-center gap-2 text-sm">
        <Link
          to={connectionPath(connectionId)}
          className="inline-flex items-center gap-1 text-text-secondary hover:text-text-primary"
        >
          <ArrowLeft className="size-3.5" aria-hidden="true" />
          {connection.data.name}
        </Link>
        <span className="text-text-disabled">/</span>
        <span className="font-medium text-text-primary">New import</span>
      </div>

      <StepIndicator step={step} />

      <div className="min-h-0 flex-1 overflow-y-auto">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={step}
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className="h-full"
          >
            {step === 1 ? (
              <div className="max-w-lg space-y-4">
                <div>
                  <h2 className="text-base font-semibold text-text-primary">
                    Where should it land?
                  </h2>
                  <p className="mt-1 text-sm text-text-secondary">
                    The import upserts every selected table into this catalog.
                  </p>
                </div>
                <label className="block space-y-1">
                  <span className="text-sm text-text">Target catalog</span>
                  <Select
                    placeholder="Choose a catalog"
                    options={catalogOptions}
                    value={targetCatalogId}
                    onChange={(event) => {
                      setTargetCatalogId(event.target.value);
                    }}
                  />
                </label>
                <label className="block space-y-1">
                  <span className="text-sm text-text">Source catalog</span>
                  <input
                    aria-label="Source catalog"
                    placeholder={connection.data.default_catalog ?? 'all catalogs'}
                    value={sourceCatalog}
                    onChange={(event) => {
                      setSourceCatalog(event.target.value);
                    }}
                    className="h-9 w-full rounded-md border border-border-strong bg-bg-surface px-3 font-mono text-sm text-text-primary outline-none focus:border-brand"
                  />
                  <span className="block text-xs text-text-disabled">
                    Leave blank to use the connection default (
                    {connection.data.default_catalog ?? 'every catalog'}).
                  </span>
                </label>
                {catalogOptions.length === 0 ? (
                  <p className="text-sm text-text-secondary">
                    No catalog exists yet — create one in the data catalog first.
                  </p>
                ) : null}
              </div>
            ) : null}

            {step === 2 ? (
              <div className="flex h-full min-h-96 flex-col gap-3">
                <p className="text-sm text-text-secondary">
                  Open a catalog and a schema, then tick the tables to import. A schema can be
                  renamed in the target catalog on the right.
                </p>
                <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_22rem]">
                  <div className="min-h-0 overflow-hidden rounded-lg border border-border-base bg-bg-surface">
                    <SourceExplorer
                      connectionId={connectionId}
                      selected={selectedKeys}
                      onToggleTable={toggleTable}
                      onToggleSchema={toggleSchema}
                    />
                  </div>
                  <div className="min-h-0 overflow-hidden rounded-lg border border-border-base bg-bg-canvas/40">
                    <ImportSelectionPanel
                      selection={selection}
                      mapping={mapping}
                      onMappingChange={(schema, target) => {
                        setMapping((current) => ({ ...current, [schema]: target }));
                      }}
                      onRemove={toggleTable}
                      onClear={() => {
                        setSelection([]);
                      }}
                    />
                  </div>
                </div>
              </div>
            ) : null}

            {step === 3 ? (
              <div className="max-w-2xl space-y-4">
                {plan.isPending ? (
                  <Skeleton lines={5} />
                ) : plan.isError ? (
                  <EmptyState
                    plain
                    title="The plan could not be computed"
                    description={plan.error instanceof Error ? plan.error.message : undefined}
                  />
                ) : plan.data === undefined ? null : (
                  <>
                    <div className="grid grid-cols-3 gap-3">
                      {[
                        { label: 'Schemas', value: plan.data.schema_count },
                        { label: 'Tables', value: plan.data.table_count },
                        { label: 'Fields', value: plan.data.field_count },
                      ].map((entry) => (
                        <div
                          key={entry.label}
                          className="rounded-lg border border-border-base bg-bg-surface px-4 py-3"
                        >
                          <p className="text-xs tracking-wide text-text-secondary uppercase">
                            {entry.label}
                          </p>
                          <p className="text-2xl font-semibold text-text-primary">{entry.value}</p>
                        </div>
                      ))}
                    </div>

                    <div className="space-y-2 rounded-lg border border-border-base bg-bg-surface p-4 text-sm">
                      <p className="flex items-center gap-1.5 text-text-primary">
                        <Sparkles className="size-4 text-brand" aria-hidden="true" />
                        {plan.data.new_schemas.length} new schema(s), {plan.data.new_tables.length}{' '}
                        new table(s), {plan.data.fields_to_change.length} field change(s)
                      </p>
                      {plan.data.new_tables.length > 0 ? (
                        <p className="text-xs text-text-secondary">
                          New: {plan.data.new_tables.slice(0, 8).join(', ')}
                          {plan.data.new_tables.length > 8 ? ' …' : ''}
                        </p>
                      ) : null}
                    </div>

                    {plan.data.unsupported_types.length > 0 ? (
                      <div className="rounded-lg border border-warning/40 bg-warning/10 p-4">
                        <p className="flex items-center gap-1.5 text-sm font-medium text-warning-ink">
                          <TriangleAlert className="size-4" aria-hidden="true" />
                          {plan.data.unsupported_types.length} column(s) cannot be mapped
                        </p>
                        <ul className="mt-1 space-y-0.5 text-xs text-text-secondary">
                          {plan.data.unsupported_types.slice(0, 6).map((row) => (
                            <li key={`${row.table}.${row.column}`} className="font-mono">
                              {row.table}.{row.column} · {row.raw_type} ({row.policy})
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}

                    {plan.data.warnings.length > 0 ? (
                      <ul className="space-y-1 text-xs text-text-secondary">
                        {plan.data.warnings.map((warning) => (
                          <li key={warning}>· {warning}</li>
                        ))}
                      </ul>
                    ) : null}

                    <p className="text-sm text-text-secondary">
                      The import writes into{' '}
                      <strong>
                        {targetCatalogId === ''
                          ? ''
                          : catalogOptions.find((option) => option.value === targetCatalogId)
                              ?.label}
                      </strong>{' '}
                      and records one run in this connection&apos;s history.
                    </p>
                  </>
                )}
              </div>
            ) : null}
          </motion.div>
        </AnimatePresence>
      </div>

      <footer className="flex items-center justify-between border-t border-border-base pt-4">
        <Button
          variant="ghost"
          onClick={() => {
            if (step === 1) {
              void navigate(connectionPath(connectionId));
              return;
            }
            setStep((value) => (value === 3 ? 2 : 1));
          }}
        >
          {step === 1 ? 'Cancel' : 'Back'}
        </Button>
        {step < 3 ? (
          <Button
            icon={<Play className="size-4" />}
            disabled={
              (step === 1 && targetCatalogId === '') || (step === 2 && selection.length === 0)
            }
            onClick={() => {
              setStep((value) => (value === 1 ? 2 : 3));
            }}
          >
            Continue
          </Button>
        ) : (
          <Button
            loading={startImport.isPending}
            disabled={plan.isError || plan.data === undefined}
            onClick={submit}
          >
            Start import
          </Button>
        )}
      </footer>

      <ProgressPanel visible={startImport.isPending} />
    </div>
  );
}
