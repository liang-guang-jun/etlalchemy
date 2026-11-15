import { useMemo, useState } from 'react';
import { ChevronRight, Search, Tag } from 'lucide-react';

import { cn } from '@/shared/lib/cn';
import { Button, Dialog, EmptyState, Input, Skeleton } from '@/shared/ui';

import { useTerms } from '../queries';
import type { TermSummary } from '../api';

export interface TermPickerProps {
  open: boolean;
  /** Domain whose tree is browsed. */
  domainId: string;
  /** Terms that cannot be picked, e.g. the moved term and its descendants. */
  excludeIds?: readonly string[];
  /** Dialog title. */
  title: string;
  /** Offers the "top level" choice, for creating or moving a term. */
  allowTopLevel?: boolean;
  /** Label of the top-level choice. */
  topLevelLabel?: string;
  /** Called with the picked term, or `null` for the top level. */
  onSelect: (term: TermSummary | null) => void;
  onClose: () => void;
}

interface FlatTerm {
  term: TermSummary;
  depth: number;
}

/**
 * Renders a browsable tree of the terms of one domain.
 *
 * @param props Component props.
 * @returns The picker dialog.
 */
export function TermPicker({
  open,
  domainId,
  excludeIds = [],
  title,
  allowTopLevel = false,
  topLevelLabel = 'Move to the top level',
  onSelect,
  onClose,
}: TermPickerProps) {
  const terms = useTerms(domainId);
  const [query, setQuery] = useState('');
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());

  const flat = useMemo<FlatTerm[]>(
    () =>
      [...(terms.data ?? [])]
        .sort((left, right) => left.path.localeCompare(right.path))
        .map((term) => ({ term, depth: term.path.split('/').length - 1 })),
    [terms.data],
  );

  const excluded = useMemo(() => new Set(excludeIds), [excludeIds]);

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (needle !== '') {
      return flat.filter(
        (row) =>
          row.term.name.toLowerCase().includes(needle) ||
          row.term.path.toLowerCase().includes(needle),
      );
    }
    return flat.filter((row) => {
      const parts = row.term.path.split('/');
      for (let index = 1; index < parts.length; index += 1) {
        if (collapsed.has(parts.slice(0, index).join('/'))) {
          return false;
        }
      }
      return true;
    });
  }, [collapsed, flat, query]);

  const toggle = (path: string) => {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  };

  return (
    <Dialog
      open={open}
      title={title}
      description="Pick a term from the tree of this domain."
      onClose={onClose}
      footer={
        <>
          {allowTopLevel ? (
            <Button
              variant="secondary"
              onClick={() => {
                onSelect(null);
                onClose();
              }}
            >
              {topLevelLabel}
            </Button>
          ) : null}
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
        </>
      }
    >
      <div className="space-y-2">
        <div className="relative">
          <Search
            className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-text-secondary"
            aria-hidden="true"
          />
          <Input
            aria-label="Filter terms"
            placeholder="Filter terms…"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
            }}
            className="pl-7"
          />
        </div>
        <div
          aria-label="Term tree"
          className="max-h-72 overflow-y-auto rounded-md border border-border-base bg-bg-surface p-1"
        >
          {terms.isPending ? <Skeleton lines={4} /> : null}
          {!terms.isPending && rows.length === 0 ? (
            <EmptyState plain title="No matching term" />
          ) : null}
          {rows.map(({ term, depth }) => {
            const hasChildren = flat.some((row) => row.term.parent_id === term.term_id);
            const isCollapsed = collapsed.has(term.path);
            const isExcluded = excluded.has(term.term_id);
            return (
              <div
                key={term.term_id}
                className="flex items-center gap-1"
                style={{ paddingLeft: 2 + depth * 12 }}
              >
                {hasChildren ? (
                  <button
                    type="button"
                    aria-label={isCollapsed ? `Expand ${term.name}` : `Collapse ${term.name}`}
                    onClick={() => {
                      toggle(term.path);
                    }}
                    className="flex size-5 shrink-0 items-center justify-center rounded-sm text-text-secondary hover:bg-bg-hover"
                  >
                    <ChevronRight
                      className={cn('size-3.5 transition-transform', !isCollapsed && 'rotate-90')}
                      aria-hidden="true"
                    />
                  </button>
                ) : (
                  <span className="size-5 shrink-0" />
                )}
                <button
                  type="button"
                  disabled={isExcluded}
                  title={
                    isExcluded
                      ? 'A term cannot move under itself or one of its descendants'
                      : term.path
                  }
                  onClick={() => {
                    onSelect(term);
                    onClose();
                  }}
                  className={cn(
                    'flex min-w-0 flex-1 items-center gap-2 rounded-sm px-2 py-1 text-left text-sm transition-colors',
                    isExcluded
                      ? 'cursor-not-allowed text-text-disabled'
                      : 'text-text-primary hover:bg-bg-hover',
                  )}
                >
                  <Tag
                    className="size-3.5 shrink-0 text-text-secondary"
                    style={term.color === '' ? undefined : { color: term.color }}
                    aria-hidden="true"
                  />
                  <span className="truncate">{term.name}</span>
                  {depth === 0 && query.trim() !== '' ? (
                    <span className="truncate text-xs text-text-disabled">{term.path}</span>
                  ) : null}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </Dialog>
  );
}
