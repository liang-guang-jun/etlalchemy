import { ArrowRight, X } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';

import { Input } from '@/shared/ui';

import type { SourceTableSelection } from '../model/selection';

export interface ImportSelectionPanelProps {
  /** Tables the user selected, in selection order. */
  selection: SourceTableSelection[];
  /** Target schema name keyed by source schema. */
  mapping: Record<string, string>;
  onMappingChange: (schema: string, target: string) => void;
  onRemove: (row: SourceTableSelection) => void;
  onClear: () => void;
}

/**
 * Renders the tables picked in the explorer, grouped by source schema so each
 * group can be renamed in the target catalog.
 *
 * @param props Component props.
 * @returns The selection panel.
 */
export function ImportSelectionPanel({
  selection,
  mapping,
  onMappingChange,
  onRemove,
  onClear,
}: ImportSelectionPanelProps) {
  const schemas = [...new Set(selection.map((row) => row.schema))];

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-border-base px-3 py-2">
        <span className="text-xs font-medium tracking-wide text-text-secondary uppercase">
          Selected {selection.length === 0 ? '' : `(${selection.length})`}
        </span>
        {selection.length > 0 ? (
          <button
            type="button"
            className="text-xs text-text-secondary hover:text-text-primary"
            onClick={onClear}
          >
            Clear
          </button>
        ) : null}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {selection.length === 0 ? (
          <p className="py-8 text-center text-sm text-text-disabled">
            Select tables on the left to build the import.
          </p>
        ) : (
          <div className="space-y-4">
            {schemas.map((schema) => {
              const rows = selection.filter((row) => row.schema === schema);
              return (
                <motion.section key={schema} layout className="space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-text-primary">{schema}</span>
                    <ArrowRight className="size-3.5 text-text-disabled" aria-hidden="true" />
                    <Input
                      aria-label={`Target schema for ${schema}`}
                      placeholder={schema}
                      value={mapping[schema] ?? ''}
                      onChange={(event) => {
                        onMappingChange(schema, event.target.value);
                      }}
                      className="h-7 w-40 text-xs"
                    />
                  </div>
                  <ul className="flex flex-wrap gap-1.5">
                    <AnimatePresence initial={false}>
                      {rows.map((row) => (
                        <motion.li
                          key={`${row.catalog}.${row.schema}.${row.table}`}
                          layout
                          initial={{ opacity: 0, scale: 0.9 }}
                          animate={{ opacity: 1, scale: 1 }}
                          exit={{ opacity: 0, scale: 0.9 }}
                          transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                          className="flex items-center gap-1 rounded-sm border border-border-base bg-bg-surface py-0.5 pl-2 pr-1 text-xs text-text-primary"
                        >
                          <span className="max-w-48 truncate">{row.table}</span>
                          <button
                            type="button"
                            aria-label={`Remove ${row.table}`}
                            className="flex size-4 items-center justify-center rounded-sm text-text-disabled hover:bg-bg-hover hover:text-danger"
                            onClick={() => {
                              onRemove(row);
                            }}
                          >
                            <X className="size-3" aria-hidden="true" />
                          </button>
                        </motion.li>
                      ))}
                    </AnimatePresence>
                  </ul>
                </motion.section>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
