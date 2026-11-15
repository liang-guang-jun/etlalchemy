import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { ChevronRight, Columns3, Database, Folder, Search, Table2 } from 'lucide-react';

import { cn } from '@/shared/lib/cn';
import { highlightMatches } from '@/shared/lib/highlight-text';
import { useDebounced } from '@/shared/lib/use-debounced';
import { Skeleton } from '@/shared/ui';

import {
  columnsByTable,
  countTables,
  filterCatalogTree,
  joinPath,
  objectKey,
  type CatalogObject,
  type CatalogObjectKind,
  type TreeColumn,
  type TreeTable,
} from '../model/object-tree';
import { useCatalogObjectSearch, useCatalogTableColumns, useCatalogTree } from '../queries';

/** Horizontal offset of one nesting level, in pixels. */
const INDENT = 12;

/** Every level can be picked unless the caller narrows it down. */
const ALL_LEVELS: readonly CatalogObjectKind[] = ['catalog', 'schema', 'table', 'field'];

interface RowProps {
  depth: number;
  label: string;
  icon: ReactNode;
  /** Search term, used to mark the matching characters of the label. */
  term: string;
  expandable?: boolean;
  expanded?: boolean;
  onToggle?: () => void;
  selectable?: boolean;
  selected?: boolean;
  onSelect?: () => void;
  trailing?: ReactNode;
}

/**
 * Renders one row of the catalog tree.
 *
 * The chevron expands and collapses; the label picks the object when its level
 * is selectable and falls back to toggling for the levels that only group.
 *
 * @param props Component props.
 * @returns The row element.
 */
function Row({
  depth,
  label,
  icon,
  term,
  expandable = false,
  expanded = false,
  onToggle,
  selectable = false,
  selected = false,
  onSelect,
  trailing,
}: RowProps) {
  return (
    <div
      className={cn(
        'flex h-8 items-center gap-1 rounded-sm border-l-2 pr-1 transition-colors',
        selected
          ? 'border-brand bg-brand/15 font-medium text-text-primary'
          : 'border-transparent text-text-secondary hover:bg-bg-hover-subtle hover:text-text-primary',
      )}
      style={{ paddingLeft: 2 + depth * INDENT }}
    >
      {expandable ? (
        <button
          type="button"
          aria-label={`${expanded ? 'Collapse' : 'Expand'} ${label}`}
          aria-expanded={expanded}
          onClick={onToggle}
          className="flex size-5 shrink-0 items-center justify-center rounded-sm text-text-secondary transition-colors hover:text-text-primary"
        >
          <ChevronRight
            className={cn('size-3.5 transition-transform', expanded && 'rotate-90')}
            aria-hidden="true"
          />
        </button>
      ) : (
        <span className="size-5 shrink-0" aria-hidden="true" />
      )}

      <button
        type="button"
        onClick={selectable ? onSelect : onToggle}
        aria-current={selected ? 'true' : undefined}
        className="flex min-w-0 flex-1 items-center gap-2 py-1 text-left text-sm"
      >
        <span className="flex shrink-0 items-center">{icon}</span>
        <span className="min-w-0 truncate">{highlightMatches(label, term)}</span>
      </button>

      {trailing === undefined ? null : (
        <span className="flex shrink-0 items-center font-mono text-[10px]">{trailing}</span>
      )}
    </div>
  );
}

interface TableNodeProps {
  catalogName: string;
  schemaName: string;
  table: TreeTable;
  depth: number;
  term: string;
  searching: boolean;
  /** Columns of this table that matched the search term. */
  hits: readonly TreeColumn[];
  open: boolean;
  onToggle: () => void;
  selectable: boolean;
  selectedKey?: string | undefined;
  onSelect: (object: CatalogObject) => void;
  fieldSelectable: boolean;
}

/**
 * Renders one table with its columns.
 *
 * While the tree is filtered the columns come from the cross-level search, so
 * the table needs no extra request; otherwise they are loaded once the table is
 * expanded.
 *
 * @param props Component props.
 * @returns The table node.
 */
function TableNode({
  catalogName,
  schemaName,
  table,
  depth,
  term,
  searching,
  hits,
  open,
  onToggle,
  selectable,
  selectedKey,
  onSelect,
  fieldSelectable,
}: TableNodeProps) {
  const key = objectKey('table', table.id);
  const path = joinPath(catalogName, schemaName, table.name);
  const columns = useCatalogTableColumns(table.id, open && !searching);
  const shown = searching ? hits : (columns.data ?? []);
  const expandable = !searching || hits.length > 0;

  return (
    <>
      <Row
        depth={depth}
        label={table.name}
        icon={<Table2 className="size-3.5" aria-hidden="true" />}
        term={term}
        expandable={expandable}
        expanded={expandable && open}
        onToggle={onToggle}
        selectable={selectable}
        selected={selectedKey === key}
        onSelect={() => {
          onSelect({
            kind: 'table',
            targetId: table.id,
            fieldName: '',
            name: table.name,
            path,
            key,
          });
        }}
      />
      {expandable && open
        ? shown.map((column) => {
            const columnKey = objectKey('field', table.id, column.name);
            return (
              <Row
                key={columnKey}
                depth={depth + 1}
                label={column.name}
                icon={<Columns3 className="size-3.5" aria-hidden="true" />}
                term={term}
                selectable={fieldSelectable}
                selected={selectedKey === columnKey}
                onSelect={() => {
                  onSelect({
                    kind: 'field',
                    targetId: table.id,
                    fieldName: column.name,
                    name: column.name,
                    path: joinPath(catalogName, schemaName, table.name, column.name),
                    key: columnKey,
                  });
                }}
                trailing={column.data_type}
              />
            );
          })
        : null}
    </>
  );
}

export interface CatalogObjectTreeProps {
  /** Called with the object the user picked. */
  onSelect: (object: CatalogObject) => void;
  /** Levels that can be picked; the others only expand and collapse. */
  selectable?: readonly CatalogObjectKind[];
  /** Object to mark as selected, built with `objectKey`. */
  selectedKey?: string;
  /** Height classes of the scrolling tree area; fixed so the dialog cannot resize. */
  className?: string;
}

/**
 * Shows the catalog as the resource explorer of the data catalog does —
 * catalog → schema → table → column — with a search that keeps the hierarchy.
 *
 * Matching nodes stay where they are, their ancestors stay visible and open, and
 * the siblings without a hit disappear. Columns are matched through
 * `GET /catalog/search-objects`, because loading every column of every table is
 * not an option; they are rendered below their table, so the path to a hit is
 * always complete.
 *
 * @param props Component props.
 * @returns The searchable tree.
 */
export function CatalogObjectTree({
  onSelect,
  selectable = ALL_LEVELS,
  selectedKey,
  className = 'h-64',
}: CatalogObjectTreeProps) {
  const [term, setTerm] = useState('');
  const [closed, setClosed] = useState<Set<string>>(() => new Set<string>());
  const [opened, setOpened] = useState<Set<string>>(() => new Set<string>());

  const { tree, isPending, isError, refetch } = useCatalogTree();
  const search = useCatalogObjectSearch(useDebounced(term, 200));
  const hits = useMemo(() => columnsByTable(search.data ?? []), [search.data]);

  const needle = term.trim().toLowerCase();
  const searching = needle !== '';
  const filtered = useMemo(() => filterCatalogTree(tree, term, hits), [tree, term, hits]);
  const tables = countTables(filtered);

  // A collapse made under one term must not hide the hits of the next one.
  useEffect(() => {
    setClosed(new Set<string>());
  }, [needle]);

  /**
   * Tells whether a node shows its children.
   *
   * @param key Key of the node.
   * @param depth Nesting level of the node.
   * @returns Whether the node is expanded.
   */
  const isOpen = (key: string, depth: number): boolean => {
    if (closed.has(key)) {
      return false;
    }
    // While filtering every surviving node is open, so a hit needs no extra
    // click; while browsing only the catalogs start open.
    return searching || depth === 0 || opened.has(key);
  };

  /**
   * Flips the expansion of one node.
   *
   * @param key Key of the node.
   * @param open Whether the node is expanded right now.
   */
  const toggle = (key: string, open: boolean): void => {
    if (open) {
      setClosed((current) => new Set(current).add(key));
      setOpened((current) => {
        const next = new Set(current);
        next.delete(key);
        return next;
      });
      return;
    }
    setClosed((current) => {
      const next = new Set(current);
      next.delete(key);
      return next;
    });
    setOpened((current) => new Set(current).add(key));
  };

  return (
    <div className="flex flex-col rounded-md border border-border-base">
      <div className="border-b border-border-base p-2">
        <div className="relative">
          <Search
            className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-text-secondary"
            aria-hidden="true"
          />
          <input
            type="search"
            aria-label="Search catalog objects"
            placeholder="Search catalogs, schemas, tables and columns…"
            value={term}
            onChange={(event) => {
              setTerm(event.target.value);
            }}
            className="h-8 w-full rounded-md border border-border-base bg-bg-hover pr-2 pl-7 text-sm text-text-primary outline-none transition-colors placeholder:text-text-disabled hover:border-border-strong focus:border-brand focus:bg-bg-surface"
          />
        </div>
      </div>

      <div className={cn('overflow-y-auto p-1', className)} aria-label="Catalog object tree">
        {isPending ? (
          <div className="p-1">
            <Skeleton lines={5} />
          </div>
        ) : isError ? (
          <p className="px-2 py-3 text-xs text-text-secondary" role="status">
            Failed to load the catalog tree.{' '}
            <button
              type="button"
              onClick={() => {
                void refetch();
              }}
              className="underline hover:text-text-primary"
            >
              Retry
            </button>
          </p>
        ) : filtered.length === 0 ? (
          <p className="px-2 py-3 text-xs text-text-secondary" role="status">
            {searching ? `No object matches “${term.trim()}”.` : 'No catalog object yet.'}
          </p>
        ) : (
          filtered.map((catalog) => {
            const catalogKey = objectKey('catalog', catalog.id);
            const catalogOpen = isOpen(catalogKey, 0);
            return (
              <div key={catalog.id}>
                <Row
                  depth={0}
                  label={catalog.name}
                  icon={<Database className="size-3.5" aria-hidden="true" />}
                  term={term}
                  expandable
                  expanded={catalogOpen}
                  onToggle={() => {
                    toggle(catalogKey, catalogOpen);
                  }}
                  selectable={selectable.includes('catalog')}
                  selected={selectedKey === catalogKey}
                  onSelect={() => {
                    onSelect({
                      kind: 'catalog',
                      targetId: catalog.id,
                      fieldName: '',
                      name: catalog.name,
                      path: catalog.name,
                      key: catalogKey,
                    });
                  }}
                />
                {catalogOpen
                  ? catalog.schemas.map((schema) => {
                      const schemaKey = objectKey('schema', schema.id);
                      const schemaOpen = isOpen(schemaKey, 1);
                      return (
                        <div key={schemaKey}>
                          <Row
                            depth={1}
                            label={schema.name}
                            icon={<Folder className="size-3.5" aria-hidden="true" />}
                            term={term}
                            expandable
                            expanded={schemaOpen}
                            onToggle={() => {
                              toggle(schemaKey, schemaOpen);
                            }}
                            selectable={selectable.includes('schema')}
                            selected={selectedKey === schemaKey}
                            onSelect={() => {
                              onSelect({
                                kind: 'schema',
                                targetId: schema.id,
                                fieldName: '',
                                name: schema.name,
                                path: joinPath(catalog.name, schema.name),
                                key: schemaKey,
                              });
                            }}
                          />
                          {schemaOpen
                            ? schema.tables.map((table) => {
                                const tableKey = objectKey('table', table.id);
                                const tableOpen = isOpen(tableKey, 2);
                                const tableHits = (hits.get(table.id) ?? []).filter((column) =>
                                  column.name.toLowerCase().includes(needle),
                                );
                                return (
                                  <TableNode
                                    key={tableKey}
                                    catalogName={catalog.name}
                                    schemaName={schema.name}
                                    table={table}
                                    depth={2}
                                    term={term}
                                    searching={searching}
                                    hits={tableHits}
                                    open={tableOpen}
                                    onToggle={() => {
                                      toggle(tableKey, tableOpen);
                                    }}
                                    selectable={selectable.includes('table')}
                                    selectedKey={selectedKey}
                                    onSelect={onSelect}
                                    fieldSelectable={selectable.includes('field')}
                                  />
                                );
                              })
                            : null}
                        </div>
                      );
                    })
                  : null}
              </div>
            );
          })
        )}
      </div>

      <p className="border-t border-border-base px-2 py-1.5 text-[11px] text-text-secondary">
        {tables} {tables === 1 ? 'table' : 'tables'}
        {searching ? ' match' : ' available'}
      </p>
    </div>
  );
}
