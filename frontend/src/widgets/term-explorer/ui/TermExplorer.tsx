import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { BookOpen, Plus, Search } from 'lucide-react';
import { useLocation } from 'react-router';

import { useDomains, type Domain } from '@/entities/domain';
import { useTerms, type TermSummary } from '@/entities/term';
import { DiscardDomainConfirm, DomainDialog } from '@/features/domain-actions';
import { CreateTermDialog, TermActionsMenu, useMoveTerm } from '@/features/term-actions';
import {
  domainPath,
  parseVocabularyPath,
  termPath,
  type VocabularyLocation,
} from '@/shared/lib/vocabulary-routes';
import { cn } from '@/shared/lib/cn';
import { ColorDot, ErrorState, Skeleton, TreeMessage, TreeRow } from '@/shared/ui';

import { TermSearchResults } from './TermSearchResults';

interface ExplorerState {
  expanded: Set<string>;
  toggle: (key: string) => void;
  expand: (keys: string[]) => void;
  location: VocabularyLocation;
  dragged: string | null;
  setDragged: (termId: string | null) => void;
}

const ExplorerContext = createContext<ExplorerState | null>(null);

/**
 * Reads the state shared by the tree rows.
 *
 * @returns The explorer state.
 */
function useExplorer(): ExplorerState {
  const state = useContext(ExplorerContext);
  if (state === null) {
    throw new Error('ExplorerContext is missing');
  }
  return state;
}

const domainKey = (domainId: string) => `domain:${domainId}`;
const termKey = (domainId: string, termId: string) => `term:${domainId}/${termId}`;

/**
 * Maps a term status to the colour of its trailing dot.
 *
 * @param status Lifecycle status.
 * @returns The dot classes.
 */
function statusDot(status: string): string {
  if (status === 'approved') {
    return 'bg-success';
  }
  if (status === 'deprecated') {
    return 'bg-danger';
  }
  return 'bg-text-disabled';
}

interface TermNodeProps {
  domainId: string;
  term: TermSummary;
  depth: number;
  childrenOf: Map<string | null, TermSummary[]>;
  onDrop: (termId: string, parentPath: string | null) => void;
}

/**
 * Renders one term and, while expanded, its direct children.
 *
 * @param props Component props.
 * @returns The term subtree.
 */
function TermNode({ domainId, term, depth, childrenOf, onDrop }: TermNodeProps) {
  const { expanded, toggle, location, dragged, setDragged } = useExplorer();
  const [creating, setCreating] = useState(false);
  const key = termKey(domainId, term.term_id);
  const open = expanded.has(key);
  const active = location.termId === term.term_id;
  const children = childrenOf.get(term.term_id) ?? [];
  const isTarget = dragged !== null && dragged !== term.term_id;

  return (
    <>
      <TreeRow
        depth={depth}
        label={term.name}
        icon={<ColorDot color={term.color} />}
        to={termPath(domainId, term.term_id)}
        active={active}
        expanded={open}
        onToggle={() => toggle(key)}
        onCreate={() => setCreating(true)}
        createLabel="New child term"
        trailing={
          <span
            title={term.status}
            aria-label={term.status}
            className={cn('block size-1.5 rounded-full', statusDot(term.status))}
          />
        }
        actions={
          <TermActionsMenu
            domainId={domainId}
            termId={term.term_id}
            name={term.name}
            status={term.status}
          />
        }
        rowProps={{
          draggable: true,
          onDragStart: (event) => {
            event.dataTransfer.setData('text/plain', term.term_id);
            event.dataTransfer.effectAllowed = 'move';
            setDragged(term.term_id);
          },
          onDragEnd: () => setDragged(null),
          onDragOver: (event) => {
            if (isTarget) {
              event.preventDefault();
              event.dataTransfer.dropEffect = 'move';
            }
          },
          onDrop: (event) => {
            event.preventDefault();
            event.stopPropagation();
            const draggedId = event.dataTransfer.getData('text/plain');
            if (draggedId !== '' && draggedId !== term.term_id) {
              onDrop(draggedId, term.path);
            }
            setDragged(null);
          },
        }}
      >
        {open ? (
          <TermList
            domainId={domainId}
            terms={children}
            depth={depth + 1}
            childrenOf={childrenOf}
            onDrop={onDrop}
          />
        ) : null}
      </TreeRow>

      <CreateTermDialog
        open={creating}
        domainId={domainId}
        parentPath={term.path}
        onClose={() => setCreating(false)}
      />
    </>
  );
}

interface TermListProps {
  domainId: string;
  terms: TermSummary[];
  depth: number;
  childrenOf: Map<string | null, TermSummary[]>;
  onDrop: (termId: string, parentPath: string | null) => void;
}

/**
 * Renders one level of terms.
 *
 * @param props Component props.
 * @returns The term rows.
 */
function TermList({ domainId, terms, depth, childrenOf, onDrop }: TermListProps) {
  return (
    <>
      {terms.map((term) => (
        <TermNode
          key={term.term_id}
          domainId={domainId}
          term={term}
          depth={depth}
          childrenOf={childrenOf}
          onDrop={onDrop}
        />
      ))}
    </>
  );
}

interface DomainNodeProps {
  domain: Domain;
  depth: number;
}

/**
 * Renders a domain and, while expanded, its term tree.
 *
 * @param props Component props.
 * @returns The domain subtree.
 */
function DomainNode({ domain, depth }: DomainNodeProps) {
  const { expanded, toggle, expand, location, dragged, setDragged } = useExplorer();
  const move = useMoveTerm(domain.domain_id);
  const [editing, setEditing] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [creating, setCreating] = useState(false);
  const key = domainKey(domain.domain_id);
  const open = expanded.has(key);
  const currentDomain = location.domainId === domain.domain_id;
  const active = currentDomain && location.termId === undefined;
  const terms = useTerms(domain.domain_id, undefined, open || currentDomain);

  const childrenOf = useMemo(() => {
    const map = new Map<string | null, TermSummary[]>();
    for (const term of terms.data ?? []) {
      const bucket = map.get(term.parent_id) ?? [];
      bucket.push(term);
      map.set(term.parent_id, bucket);
    }
    return map;
  }, [terms.data]);

  // Keep the branch that leads to the term in the URL open.
  useEffect(() => {
    if (!currentDomain || location.termId === undefined || terms.data === undefined) {
      return;
    }
    const byId = new Map(terms.data.map((term) => [term.term_id, term]));
    const keys = [key];
    let cursor = byId.get(location.termId);
    while (cursor !== undefined) {
      keys.push(termKey(domain.domain_id, cursor.term_id));
      cursor = cursor.parent_id === null ? undefined : byId.get(cursor.parent_id);
    }
    expand(keys);
  }, [currentDomain, location.termId, terms.data, domain.domain_id, key, expand]);

  const onDrop = (termId: string, parentPath: string | null): void => {
    move.mutate({ termId, newParent: parentPath });
  };

  return (
    <>
      <TreeRow
        depth={depth}
        label={domain.name}
        icon={<BookOpen className="size-3.5" aria-hidden="true" />}
        to={domainPath(domain.domain_id)}
        active={active}
        expanded={open}
        onToggle={() => toggle(key)}
        onCreate={() => setCreating(true)}
        createLabel="New term"
        menuItems={[
          { label: 'Rename / edit', onSelect: () => setEditing(true) },
          { label: 'Delete domain', danger: true, onSelect: () => setDiscarding(true) },
        ]}
        rowProps={{
          onDragOver: (event) => {
            if (dragged !== null) {
              event.preventDefault();
              event.dataTransfer.dropEffect = 'move';
            }
          },
          onDrop: (event) => {
            event.preventDefault();
            const draggedId = event.dataTransfer.getData('text/plain');
            if (draggedId !== '') {
              onDrop(draggedId, null);
            }
            setDragged(null);
          },
        }}
      >
        {open ? (
          terms.isPending ? (
            <TreeMessage depth={depth + 1} text="Loading…" />
          ) : terms.isError ? (
            <TreeMessage depth={depth + 1} text="Failed to load terms" />
          ) : (terms.data ?? []).length === 0 ? (
            <TreeMessage depth={depth + 1} text="No terms yet" />
          ) : (
            <div
              onDragOver={(event) => {
                if (dragged !== null) {
                  event.preventDefault();
                }
              }}
              onDrop={(event) => {
                event.preventDefault();
                const draggedId = event.dataTransfer.getData('text/plain');
                if (draggedId !== '') {
                  onDrop(draggedId, null);
                }
                setDragged(null);
              }}
            >
              <TermList
                domainId={domain.domain_id}
                terms={childrenOf.get(null) ?? []}
                depth={depth + 1}
                childrenOf={childrenOf}
                onDrop={onDrop}
              />
            </div>
          )
        ) : null}
      </TreeRow>

      <CreateTermDialog
        open={creating}
        domainId={domain.domain_id}
        onClose={() => setCreating(false)}
      />
      <DomainDialog
        open={editing}
        onClose={() => setEditing(false)}
        initial={{
          domainId: domain.domain_id,
          name: domain.name,
          description: domain.description,
        }}
      />
      <DiscardDomainConfirm
        open={discarding}
        domainId={domain.domain_id}
        name={domain.name}
        onClose={() => setDiscarding(false)}
        onDiscarded={() => setDiscarding(false)}
      />
    </>
  );
}

/**
 * Renders the business-terms explorer: a search box over the focused result
 * list, a flat domain list and, under every domain, its nested term tree.
 *
 * @returns The vocabulary sidebar.
 */
export function TermExplorer() {
  const location = useLocation();
  const parsed = useMemo(() => parseVocabularyPath(location.pathname), [location.pathname]);
  const domains = useDomains();
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set<string>());
  const [createOpen, setCreateOpen] = useState(false);
  const [term, setTerm] = useState('');
  const [dragged, setDragged] = useState<string | null>(null);
  const query = term.trim();
  const searching = query.length >= 1;

  useEffect(() => {
    if (parsed.domainId === undefined) {
      return;
    }
    setExpanded((current) => {
      const key = domainKey(parsed.domainId ?? '');
      if (current.has(key)) {
        return current;
      }
      const next = new Set(current);
      next.add(key);
      return next;
    });
  }, [parsed.domainId]);

  const toggle = useCallback((key: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  const expand = useCallback((keys: string[]) => {
    setExpanded((current) => {
      const missing = keys.filter((key) => !current.has(key));
      if (missing.length === 0) {
        return current;
      }
      const next = new Set(current);
      for (const key of missing) {
        next.add(key);
      }
      return next;
    });
  }, []);

  const state = useMemo<ExplorerState>(
    () => ({ expanded, toggle, expand, location: parsed, dragged, setDragged }),
    [expanded, toggle, expand, parsed, dragged],
  );

  return (
    <ExplorerContext.Provider value={state}>
      <div className="flex h-full min-h-0 flex-col">
        <div className="flex shrink-0 items-center gap-2 px-2 py-2">
          <div className="relative min-w-0 flex-1">
            <Search
              className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-text-secondary"
              aria-hidden="true"
            />
            <input
              type="search"
              aria-label="Search terms"
              placeholder="Search terms…"
              value={term}
              onChange={(event) => {
                setTerm(event.target.value);
              }}
              className="h-8 w-full rounded-md border border-border-base bg-bg-hover pl-7 pr-2 text-sm text-text-primary outline-none transition-colors placeholder:text-text-disabled hover:border-border-strong focus:border-brand focus:bg-bg-surface focus:shadow-sm"
            />
          </div>
          <button
            type="button"
            aria-label="New domain"
            title="New domain"
            onClick={() => {
              setCreateOpen(true);
            }}
            className="flex size-8 shrink-0 items-center justify-center rounded-md text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
          >
            <Plus className="size-4" aria-hidden="true" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2" aria-label="Term tree">
          {searching ? (
            <TermSearchResults query={query} />
          ) : domains.isPending ? (
            <Skeleton lines={6} />
          ) : domains.isError ? (
            <ErrorState
              detail={domains.error instanceof Error ? domains.error.message : undefined}
              onRetry={() => {
                void domains.refetch();
              }}
            />
          ) : (domains.data ?? []).length === 0 ? (
            <p className="px-2 py-4 text-xs text-text-secondary">
              No domains yet. Use the + button to create the first one.
            </p>
          ) : (
            (domains.data ?? []).map((domain) => (
              <DomainNode key={domain.domain_id} domain={domain} depth={0} />
            ))
          )}
        </div>

        <DomainDialog open={createOpen} onClose={() => setCreateOpen(false)} />
      </div>
    </ExplorerContext.Provider>
  );
}
