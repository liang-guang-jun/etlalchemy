import { Handle, Position, type Node, type NodeProps } from '@xyflow/react';
import { Table2 } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { useLayoutEffect, useMemo, useRef, useState } from 'react';

import { useTableFields } from '@/entities/field';
import { useTableLocation } from '@/entities/table';
import { cn } from '@/shared/lib/cn';
import { tablePath } from '@/shared/lib/catalog-routes';

import type { EntityDetailLevel } from '../model/detail-level';
import { orderColumns, type ColumnRow } from '../model/highlight';

/** Data carried by one entity card on the canvas. */
export interface EntityNodeData extends Record<string, unknown> {
  /** Name of the entity. */
  label: string;
  /** Id of the catalog table the entity maps to. */
  tableId: string;
  /** Whether the inspector is currently showing this entity. */
  active: boolean;
  /** How much of the card is expanded. */
  detailLevel: EntityDetailLevel;
  /** Columns of this entity that relationships reference. */
  relationFields: string[];
  /** Columns of the highlighted relationship that belong to this entity. */
  highlightFields: string[];
  /** Whether the highlighted relationship touches this entity. */
  highlighted: boolean;
}

/** Node type of an entity card. */
export type EntityFlowNode = Node<EntityNodeData, 'entity'>;

/** Rows shown before the column list starts scrolling. */
const MAX_VISIBLE_COLUMNS = 5;

/** Vertical pitch of one column row: `leading-4` (16px) plus the 2px gap. */
const COLUMN_ROW_PITCH = 18;

/** Top padding and border of the list, so ten rows fit exactly. */
const LIST_CHROME = 8;

/** Height after which the column list scrolls instead of growing. */
const LIST_MAX_HEIGHT = MAX_VISIBLE_COLUMNS * COLUMN_ROW_PITCH + LIST_CHROME;

/**
 * Renders one entity as a card with its table below the name.
 *
 * The card grows with the chosen detail level: the table path only, the columns
 * relationships use, or every column of the table. The column list animates its
 * height so switching levels never jumps, shows at most ten rows and scrolls
 * inside for the rest, and lifts the columns of a highlighted relationship to
 * the top with a layout animation.
 *
 * @param props Node props provided by React Flow.
 * @returns The entity card.
 */
export function EntityNodeView({ data }: NodeProps<EntityFlowNode>) {
  const location = useTableLocation(data.tableId);
  const table = location.data;
  const allFields = useTableFields(data.detailLevel === 'all' ? data.tableId : '');

  const columns = useMemo<ColumnRow[]>(() => {
    if (data.detailLevel === 'all') {
      return (allFields.data ?? []).map((field) => ({
        name: field.name,
        dataType: field.data_type,
      }));
    }
    if (data.detailLevel === 'relations') {
      return data.relationFields.map((name) => ({ name, dataType: '' }));
    }
    return [];
  }, [data.detailLevel, data.relationFields, allFields.data]);

  // While the first "all columns" response is on its way the previous rows stay
  // visible, so the card grows once instead of collapsing and expanding again.
  const loadingAll = data.detailLevel === 'all' && allFields.isPending;
  const [previousColumns, setPreviousColumns] = useState<ColumnRow[]>([]);
  const displayColumns = loadingAll ? previousColumns : columns;
  // A highlighted relationship lifts its own columns to the top, so they are
  // visible even when the list has to scroll.
  const visibleColumns = useMemo(
    () => orderColumns(displayColumns, data.highlightFields),
    [displayColumns, data.highlightFields],
  );

  // `height: auto` cannot be interpolated, so the content is measured and the
  // list animates towards that height. The measurement reads an inner wrapper,
  // because `scrollHeight` of the animated box would never shrink below it.
  const contentRef = useRef<HTMLDivElement>(null);
  const [contentHeight, setContentHeight] = useState(0);
  const signature = displayColumns.map((column) => column.name).join('|');

  useLayoutEffect(() => {
    if (!loadingAll) {
      setPreviousColumns(columns);
    }
  }, [loadingAll, columns]);

  useLayoutEffect(() => {
    if (contentRef.current !== null) {
      setContentHeight(contentRef.current.offsetHeight);
    }
  }, [signature]);

  return (
    <div
      className={cn(
        'min-w-44 max-w-64 rounded-lg border bg-bg-surface px-3 py-2 shadow-sm transition-shadow',
        data.active
          ? 'border-brand ring-2 ring-brand/50'
          : data.highlighted
            ? 'border-brand ring-2 ring-brand/25'
            : 'border-border-strong hover:border-brand/60',
      )}
    >
      <Handle type="target" position={Position.Left} isConnectable={false} className="opacity-0" />
      <p className="truncate text-sm font-semibold text-text-primary">{data.label}</p>
      <p className="mt-0.5 flex min-w-0 items-center gap-1 text-[10px] text-text-secondary">
        <Table2 className="size-3 shrink-0 text-text-disabled" aria-hidden="true" />
        {table === undefined ? (
          <span className="truncate font-mono">
            {data.tableId === '' ? 'no table' : `table ${data.tableId.slice(0, 8)}`}
          </span>
        ) : (
          <a
            href={tablePath(table.catalog_id, table.schema_name, table.name)}
            target="_blank"
            rel="noreferrer"
            title={`Open ${table.schema_name}.${table.name} in the catalog`}
            aria-label={`Open ${table.schema_name}.${table.name} in the catalog`}
            onClick={(event) => {
              event.stopPropagation();
            }}
            className="nodrag nopan min-w-0 truncate font-mono underline-offset-2 hover:text-text-primary hover:underline"
          >
            {table.schema_name}.{table.name}
          </a>
        )}
      </p>
      <AnimatePresence initial={false}>
        {visibleColumns.length > 0 ? (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: contentHeight, opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className="mt-1.5 overflow-hidden"
          >
            {/* Scrolls inside the card, but without a visible bar: the list
                still scrolls with the wheel and keeps its width stable. */}
            <div
              ref={contentRef}
              style={{ maxHeight: LIST_MAX_HEIGHT, scrollbarWidth: 'none' }}
              className="nowheel space-y-0.5 overflow-y-auto overscroll-contain border-t border-border-base pt-1.5 [&::-webkit-scrollbar]:hidden"
            >
              {visibleColumns.map((column) => {
                const highlighted = data.highlightFields.includes(column.name);
                return (
                  <motion.div
                    layout
                    key={column.name}
                    transition={{ duration: 0.2, ease: 'easeOut' }}
                    className={cn(
                      'flex items-center gap-2 rounded text-[10px] leading-4',
                      highlighted && 'bg-brand/15 px-1',
                    )}
                  >
                    <span
                      className={cn(
                        'min-w-0 flex-1 truncate font-mono',
                        highlighted ? 'font-medium text-text-primary' : 'text-text-secondary',
                      )}
                    >
                      {column.name}
                    </span>
                    {column.dataType === '' ? null : (
                      <span className="shrink-0 text-text-disabled">{column.dataType}</span>
                    )}
                  </motion.div>
                );
              })}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
      <Handle type="source" position={Position.Right} isConnectable={false} className="opacity-0" />
    </div>
  );
}
