import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { ChevronRight, Search, Tag } from 'lucide-react';

import { useDomains, type Domain } from '@/entities/domain';
import {
  buildTermTree,
  flattenTermTree,
  searchSources,
  summarySources,
  useTerms,
  useTermSearch,
  type TermTreeNode,
} from '@/entities/term';
import { cn } from '@/shared/lib/cn';
import { highlightMatches } from '@/shared/lib/highlight-text';
import { useDebounced } from '@/shared/lib/use-debounced';
import { Skeleton } from '@/shared/ui';

/** Horizontal offset of one nesting level, in pixels. */
const INDENT = 12;

/** One term picked from the tree. */
export interface TermSelection {
  /** Id of the domain that owns the term. */
  domainId: string;
  /** Name of the owning domain. */
  domainName: string;
  /** Id of the term. */
  termId: string;
  /** Name of the term. */
  name: string;
  /** Full path of the term inside its domain. */
  path: string;
}

interface RowProps {
  /** Nesting level, used for the indentation. */
  depth: number;
  /** Text of the row. */
  label: string;
  /** Icon shown before the label. */
  icon: ReactNode;
  /** Search text, used to mark the matching characters. */
  term: string;
  /** Whether the row has children and therefore shows a chevron. */
  expandable?: boolean;
  /** Whether the children are visible right now. */
  expanded?: boolean;
  /** Called by the chevron. */
  onToggle?: () => void;
  /** Called by the label when the row can be picked. */
  onPick?: () => void;
  /** Why the row cannot be picked, shown on hover. */
  disabledReason?: string;
  /** Secondary text shown at the end of the row. */
  trailing?: ReactNode;
}

/**
 * Renders one row of the term tree.
 *
 * The chevron expands and collapses; the label picks the term, so a parent term
 * stays both browsable and selectable.
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
  onPick,
  disabledReason,
  trailing,
}: RowProps) {
  const disabled = onPick === undefined;

  return (
    <div
      className="flex h-8 items-center gap-1 rounded-sm pr-1 transition-colors hover:bg-bg-hover-subtle"
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
        onClick={onPick ?? onToggle}
        disabled={disabled && !expandable}
        title={disabled ? disabledReason : undefined}
        className={cn(
          'flex min-w-0 flex-1 items-center gap-2 py-1 text-left text-sm',
          disabled ? 'text-text-disabled' : 'text-text-secondary hover:text-text-primary',
        )}
      >
        <span className="flex shrink-0 items-center">{icon}</span>
        <span className="min-w-0 truncate">{highlightMatches(label, term)}</span>
      </button>

      {trailing === undefined ? null : (
        <span className="flex shrink-0 items-center font-mono text-[10px] text-text-disabled">
          {trailing}
        </span>
      )}
    </div>
  );
}

/**
 * Tells whether a node can be linked.
 *
 * Linking is an edit of the term, so only drafts accept it; the other rows stay
 * visible but cannot be picked.
 *
 * @param node Node to check.
 * @returns The reason the node cannot be picked, or `undefined` when it can.
 */
function unpickableReason(node: TermTreeNode): string | undefined {
  if (node.termId === null) {
    return undefined;
  }
  if (node.status !== 'draft') {
    return `Only draft terms can be linked (this one is ${node.status ?? 'unknown'})`;
  }
  return undefined;
}

interface TermRowsProps {
  nodes: readonly TermTreeNode[];
  term: string;
  collapsed: ReadonlySet<string>;
  onToggle: (key: string) => void;
  onPick: (node: TermTreeNode) => void;
}

/**
 * Renders the visible rows of a term subtree.
 *
 * @param props Component props.
 * @returns The rows.
 */
function TermRows({ nodes, term, collapsed, onToggle, onPick }: TermRowsProps) {
  return (
    <>
      {flattenTermTree(nodes, collapsed).map((node) => {
        const expandable = node.children.length > 0;
        const expanded = expandable && !collapsed.has(node.key);
        const reason = unpickableReason(node);
        const pickable = node.termId !== null && reason === undefined;
        return (
          <Row
            key={node.key}
            depth={node.depth}
            label={node.label}
            term={term}
            icon={<Tag className="size-3.5" aria-hidden="true" />}
            expandable={expandable}
            expanded={expanded}
            onToggle={() => {
              onToggle(node.key);
            }}
            onPick={
              pickable
                ? () => {
                    onPick(node);
                  }
                : undefined
            }
            disabledReason={reason}
            trailing={node.status === null || node.status === 'draft' ? undefined : node.status}
          />
        );
      })}
    </>
  );
}

interface DomainNodeProps {
  domain: Domain;
  term: string;
  onPick: (selection: TermSelection) => void;
}

/**
 * Loads and renders the terms of one domain.
 *
 * The request runs when the domain is expanded, so opening the browser does not
 * read every domain of the vocabulary.
 *
 * @param props Component props.
 * @returns The rows of the domain.
 */
function DomainNode({ domain, term, onPick }: DomainNodeProps) {
  const terms = useTerms(domain.domain_id);
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(() => new Set());

  const nodes = useMemo(
    () => buildTermTree(summarySources(domain, terms.data ?? []))[0]?.children ?? [],
    [domain, terms.data],
  );

  if (terms.isPending) {
    return <Skeleton lines={3} />;
  }
  if (terms.isError) {
    return (
      <p className="px-2 py-2 text-xs text-text-secondary" role="status">
        Failed to load the terms of this domain.
      </p>
    );
  }
  if (nodes.length === 0) {
    return (
      <p className="px-2 py-2 text-xs text-text-secondary" role="status">
        This domain has no term yet.
      </p>
    );
  }

  return (
    <TermRows
      nodes={nodes}
      term={term}
      collapsed={collapsed}
      onToggle={(key) => {
        setCollapsed((current) => {
          const next = new Set(current);
          if (next.has(key)) {
            next.delete(key);
          } else {
            next.add(key);
          }
          return next;
        });
      }}
      onPick={(node) => {
        if (node.termId === null) {
          return;
        }
        onPick({
          domainId: node.domainId,
          domainName: node.domainName,
          termId: node.termId,
          name: node.label,
          path: node.path,
        });
      }}
    />
  );
}

export interface TermTreeProps {
  /** Called with the term the user picked. */
  onPick: (selection: TermSelection) => void;
  /** Height classes of the scrolling tree area. */
  className?: string;
}

/**
 * Browses the vocabulary — domain → term → sub-term — with a keyword search.
 *
 * The tree is the counterpart of the catalog picker: while the search box is
 * empty it starts at the domains and loads a domain's terms only when the domain
 * is expanded, and once a keyword is typed every hit arrives with its ancestors,
 * so the path of a match is always visible.
 *
 * @param props Component props.
 * @returns The searchable term tree.
 */
export function TermTree({ onPick, className = 'h-72' }: TermTreeProps) {
  const domains = useDomains();
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set());
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(() => new Set());
  const debounced = useDebounced(query, 200);
  const search = useTermSearch(debounced);
  const needle = query.trim().toLowerCase();
  const searching = needle !== '';

  // A collapse made under one keyword must not hide the hits of the next one.
  useEffect(() => {
    setCollapsed(new Set());
  }, [needle]);

  const nodes = useMemo(
    () => (searching ? buildTermTree(searchSources(search.data ?? [])) : []),
    [searching, search.data],
  );

  /**
   * Expands or collapses one domain row.
   *
   * @param key Key of the domain row.
   */
  const toggleDomain = (key: string): void => {
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  /**
   * Expands or collapses one row of the search tree.
   *
   * @param key Key of the row.
   */
  const toggleHit = (key: string): void => {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  /**
   * Reports one picked node to the caller.
   *
   * @param node Node the user clicked.
   */
  const pick = (node: TermTreeNode): void => {
    if (node.termId === null) {
      return;
    }
    onPick({
      domainId: node.domainId,
      domainName: node.domainName,
      termId: node.termId,
      name: node.label,
      path: node.path,
    });
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
            aria-label="Search terms"
            placeholder="Search terms by name, definition or alias…"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
            }}
            className="h-8 w-full rounded-md border border-border-base bg-bg-hover pr-2 pl-7 text-sm text-text-primary outline-none transition-colors placeholder:text-text-disabled hover:border-border-strong focus:border-brand focus:bg-bg-surface"
          />
        </div>
      </div>

      <div className={cn('overflow-y-auto p-1', className)} aria-label="Term tree">
        {searching ? (
          search.isPending ? (
            <div className="p-1">
              <Skeleton lines={5} />
            </div>
          ) : nodes.length === 0 ? (
            <p className="px-2 py-3 text-xs text-text-secondary" role="status">
              No term matches “{query.trim()}”.
            </p>
          ) : (
            <TermRows
              nodes={nodes}
              term={query}
              collapsed={collapsed}
              onToggle={toggleHit}
              onPick={pick}
            />
          )
        ) : domains.isPending ? (
          <div className="p-1">
            <Skeleton lines={4} />
          </div>
        ) : domains.isError ? (
          <p className="px-2 py-3 text-xs text-text-secondary" role="status">
            Failed to load the vocabulary.
          </p>
        ) : (domains.data ?? []).length === 0 ? (
          <p className="px-2 py-3 text-xs text-text-secondary" role="status">
            No domain yet.
          </p>
        ) : (
          (domains.data ?? []).map((domain) => {
            const expanded = open.has(domain.domain_id);
            return (
              <div key={domain.domain_id}>
                <Row
                  depth={0}
                  label={domain.name}
                  term=""
                  icon={<Tag className="size-3.5" aria-hidden="true" />}
                  expandable
                  expanded={expanded}
                  onToggle={() => {
                    toggleDomain(domain.domain_id);
                  }}
                />
                {expanded ? <DomainNode domain={domain} term="" onPick={onPick} /> : null}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
