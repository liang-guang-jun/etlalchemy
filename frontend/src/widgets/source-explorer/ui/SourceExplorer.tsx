import { useEffect, useState, type MouseEvent, type ReactNode } from 'react';
import { ChevronRight, Database, Folder, Loader2, Table2 } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';

import { useSourceInspect } from '@/entities/ingestion';
import { cn } from '@/shared/lib/cn';

import { tableKey, type SourceTableSelection } from '../model/selection';

export interface SourceExplorerProps {
  connectionId: string;
  /** Keys of the tables that are already selected. */
  selected: ReadonlySet<string>;
  onToggleTable: (row: SourceTableSelection) => void;
  /** Selects or clears every table of one schema at once. */
  onToggleSchema: (rows: SourceTableSelection[], select: boolean) => void;
}

interface RowProps {
  label: string;
  depth: number;
  icon: ReactNode;
  open?: boolean;
  onClick?: (event: MouseEvent<HTMLDivElement>) => void;
  trailing?: ReactNode;
}

/**
 * Renders one expandable tree row.
 *
 * @param props Component props.
 * @returns The row element.
 */
function TreeRow({ label, depth, icon, open, onClick, trailing }: RowProps) {
  return (
    <div
      className={cn(
        'group/row flex items-center gap-1.5 rounded-sm py-1 pr-2 text-sm',
        onClick === undefined ? '' : 'cursor-pointer hover:bg-bg-hover',
      )}
      style={{ paddingLeft: `${depth * 14 + 6}px` }}
      onClick={onClick}
      role={onClick === undefined ? undefined : 'button'}
    >
      {open === undefined ? (
        <span className="size-3.5" aria-hidden="true" />
      ) : (
        <motion.span animate={{ rotate: open ? 90 : 0 }} transition={{ duration: 0.15 }}>
          <ChevronRight className="size-3.5 text-text-secondary" aria-hidden="true" />
        </motion.span>
      )}
      <span className="text-text-secondary">{icon}</span>
      <span className="min-w-0 flex-1 truncate text-text-primary">{label}</span>
      {trailing}
    </div>
  );
}

/**
 * Renders a checkbox whose tick bounces when it is pressed.
 *
 * @param props Component props.
 * @returns The checkbox element.
 */
function TreeCheckbox({
  checked,
  mixed = false,
  disabled = false,
  onChange,
}: {
  checked: boolean;
  mixed?: boolean;
  disabled?: boolean;
  onChange: () => void;
}) {
  return (
    <motion.button
      type="button"
      role="checkbox"
      aria-checked={mixed ? 'mixed' : checked}
      disabled={disabled}
      whileTap={disabled ? undefined : { scale: 0.8 }}
      onClick={(event) => {
        event.stopPropagation();
        onChange();
      }}
      className={cn(
        'flex size-4 shrink-0 items-center justify-center rounded-[4px] border transition-colors',
        checked || mixed
          ? 'border-brand bg-brand text-brand-text'
          : 'border-border-strong bg-bg-surface text-transparent hover:border-brand',
        disabled && 'cursor-not-allowed opacity-40',
      )}
    >
      {checked ? (
        <svg viewBox="0 0 12 12" className="size-2.5" aria-hidden="true">
          <path
            d="M2 6.5 4.5 9 10 3.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      ) : mixed ? (
        <span className="h-0.5 w-2 rounded-full bg-current" aria-hidden="true" />
      ) : null}
    </motion.button>
  );
}

interface SchemaNodeProps extends SourceExplorerProps {
  catalog: string;
  schema: string;
  depth: number;
}

/**
 * Renders one schema with its lazily loaded tables.
 *
 * @param props Component props.
 * @returns The schema node.
 */
function SchemaNode({
  connectionId,
  catalog,
  schema,
  depth,
  selected,
  onToggleTable,
  onToggleSchema,
}: SchemaNodeProps) {
  const [open, setOpen] = useState(false);
  const [selectAll, setSelectAll] = useState(false);
  const tables = useSourceInspect(connectionId, { catalog, schema }, open);
  const names = (tables.data?.items ?? []).map((item) => item.name);
  const rows = names.map((table) => ({ catalog, schema, table }));
  const selectedCount = rows.filter((row) => selected.has(tableKey(row))).length;

  useEffect(() => {
    if (!selectAll || tables.data === undefined) {
      return;
    }
    onToggleSchema(
      tables.data.items.map((item) => ({ catalog, schema, table: item.name })),
      true,
    );
    setSelectAll(false);
  }, [catalog, onToggleSchema, schema, selectAll, tables.data]);

  return (
    <li>
      <TreeRow
        label={schema}
        depth={depth}
        icon={<Folder className="size-3.5" aria-hidden="true" />}
        open={open}
        onClick={(event) => {
          setOpen((value) => !value);
          event.currentTarget.scrollIntoView({ block: 'nearest' });
        }}
        trailing={
          <span className="flex items-center gap-2">
            {selectedCount > 0 ? (
              <span className="text-[11px] text-text-secondary">{selectedCount} selected</span>
            ) : null}
            <TreeCheckbox
              checked={names.length > 0 && selectedCount === names.length}
              mixed={selectedCount > 0 && selectedCount < names.length}
              onChange={() => {
                if (!open || tables.data === undefined) {
                  setOpen(true);
                  setSelectAll(true);
                  return;
                }
                onToggleSchema(rows, selectedCount !== names.length);
              }}
            />
          </span>
        }
      />
      <AnimatePresence initial={false}>
        {open ? (
          <motion.ul
            key="children"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className="overflow-hidden"
          >
            {tables.isPending ? (
              <li
                className="flex items-center gap-2 py-1 text-xs text-text-secondary"
                style={{ paddingLeft: `${(depth + 1) * 14 + 26}px` }}
              >
                <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
                Loading tables…
              </li>
            ) : tables.isError ? (
              <li
                className="py-1 text-xs text-danger"
                style={{ paddingLeft: `${(depth + 1) * 14 + 26}px` }}
              >
                The source did not answer for this schema.
              </li>
            ) : names.length === 0 ? (
              <li
                className="py-1 text-xs text-text-disabled"
                style={{ paddingLeft: `${(depth + 1) * 14 + 26}px` }}
              >
                No tables
              </li>
            ) : (
              rows.map((row) => {
                const checked = selected.has(tableKey(row));
                return (
                  <li key={row.table}>
                    <div
                      className="flex items-center gap-2 rounded-sm py-1 pr-2 hover:bg-bg-hover"
                      style={{ paddingLeft: `${(depth + 1) * 14 + 12}px` }}
                    >
                      <TreeCheckbox
                        checked={checked}
                        onChange={() => {
                          onToggleTable(row);
                        }}
                      />
                      <button
                        type="button"
                        className="flex min-w-0 flex-1 items-center gap-1.5 text-left text-sm"
                        onClick={() => {
                          onToggleTable(row);
                        }}
                      >
                        <Table2 className="size-3.5 text-text-secondary" aria-hidden="true" />
                        <span className="truncate text-text-primary">{row.table}</span>
                      </button>
                    </div>
                  </li>
                );
              })
            )}
          </motion.ul>
        ) : null}
      </AnimatePresence>
    </li>
  );
}

interface CatalogNodeProps extends SourceExplorerProps {
  catalog: string;
}

/**
 * Renders one source catalog with its lazily loaded schemas.
 *
 * @param props Component props.
 * @returns The catalog node.
 */
function CatalogNode({
  connectionId,
  catalog,
  selected,
  onToggleTable,
  onToggleSchema,
}: CatalogNodeProps) {
  const [open, setOpen] = useState(false);
  const schemas = useSourceInspect(connectionId, { catalog }, open);

  return (
    <li>
      <TreeRow
        label={catalog}
        depth={0}
        icon={<Database className="size-3.5" aria-hidden="true" />}
        open={open}
        onClick={(event) => {
          setOpen((value) => !value);
          event.currentTarget.scrollIntoView({ block: 'nearest' });
        }}
      />
      <AnimatePresence initial={false}>
        {open ? (
          <motion.ul
            key="children"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className="overflow-hidden"
          >
            {schemas.isPending ? (
              <li className="flex items-center gap-2 py-1 pl-8 text-xs text-text-secondary">
                <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
                Loading schemas…
              </li>
            ) : schemas.isError ? (
              <li className="py-1 pl-8 text-xs text-danger">
                The source did not answer for this catalog.
              </li>
            ) : (
              (schemas.data?.items ?? []).map((item) => (
                <SchemaNode
                  key={item.name}
                  connectionId={connectionId}
                  catalog={catalog}
                  schema={item.name}
                  depth={1}
                  selected={selected}
                  onToggleTable={onToggleTable}
                  onToggleSchema={onToggleSchema}
                />
              ))
            )}
          </motion.ul>
        ) : null}
      </AnimatePresence>
    </li>
  );
}

/**
 * Renders the explorable catalogs of one source connection.
 *
 * Every level is loaded on demand through the inspect route, so a large source
 * costs nothing until it is opened. The tree fills the height its host gives it
 * and scrolls inside, so a deep structure never grows the surrounding page.
 *
 * @param props Component props.
 * @returns The explorer panel.
 */
export function SourceExplorer({
  connectionId,
  selected,
  onToggleTable,
  onToggleSchema,
}: SourceExplorerProps) {
  const catalogs = useSourceInspect(connectionId, {});
  const items = catalogs.data?.items ?? [];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain py-1"
        aria-label="Source tree"
      >
        {catalogs.isPending ? (
          <div className="flex items-center gap-2 px-3 py-4 text-sm text-text-secondary">
            <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            Connecting to the source…
          </div>
        ) : catalogs.isError ? (
          <p className="px-3 py-4 text-sm text-danger">
            {catalogs.error instanceof Error ? catalogs.error.message : 'The source did not answer'}
          </p>
        ) : items.length === 0 ? (
          <p className="px-3 py-4 text-sm text-text-disabled">The source exposes no catalog.</p>
        ) : (
          <ul>
            {items.map((item) => (
              <CatalogNode
                key={item.name}
                connectionId={connectionId}
                catalog={item.name}
                selected={selected}
                onToggleTable={onToggleTable}
                onToggleSchema={onToggleSchema}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
