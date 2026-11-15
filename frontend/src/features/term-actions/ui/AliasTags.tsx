import { useRef, useState, type KeyboardEvent } from 'react';
import { Plus, X } from 'lucide-react';

import type { Term } from '@/entities/term';
import { cn } from '@/shared/lib/cn';

import { useChangeTerm } from '../api/mutation';

export interface AliasTagsProps {
  domainId: string;
  term: Term;
  /** Aliases are editable while the term is a draft. */
  editable?: boolean;
}

/**
 * Renders the aliases of a term as removable pills with an inline "add" pill.
 *
 * @param props Component props.
 * @returns The alias tag list.
 */
export function AliasTags({ domainId, term, editable = false }: AliasTagsProps) {
  const mutation = useChangeTerm(domainId, term.term_id);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const startAdding = () => {
    setDraft('');
    setAdding(true);
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  const commit = () => {
    const alias = draft.trim();
    setAdding(false);
    setDraft('');
    if (alias === '' || term.aliases.includes(alias)) {
      return;
    }
    mutation.mutate({ aliases_add: [alias] });
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      commit();
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      setAdding(false);
      setDraft('');
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-1.5" aria-label="Aliases">
      {term.aliases.map((alias) => (
        <span
          key={alias}
          className="group/alias inline-flex items-center gap-1 rounded-full border border-border-base bg-bg-hover-subtle py-0.5 pr-1 pl-2 text-xs font-medium text-text-secondary"
        >
          {alias}
          {editable ? (
            <button
              type="button"
              aria-label={`Remove alias ${alias}`}
              title={`Remove ${alias}`}
              disabled={mutation.isPending}
              onClick={() => {
                mutation.mutate({ aliases_remove: [alias] });
              }}
              className="flex size-4 items-center justify-center rounded-full text-text-disabled transition-colors hover:bg-danger/10 hover:text-danger disabled:cursor-not-allowed"
            >
              <X className="size-2.5" aria-hidden="true" />
            </button>
          ) : null}
        </span>
      ))}
      {!editable ? null : adding ? (
        <input
          ref={inputRef}
          aria-label="New alias"
          placeholder="Alias…"
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value);
          }}
          onKeyDown={onKeyDown}
          onBlur={commit}
          className="h-6 w-28 rounded-full border border-brand bg-bg-surface px-2 text-xs text-text-primary outline-none placeholder:text-text-disabled"
        />
      ) : (
        <button
          type="button"
          aria-label="Add alias"
          onClick={startAdding}
          className={cn(
            'inline-flex h-6 items-center gap-1 rounded-full border border-dashed border-border-strong px-2 text-xs text-text-secondary transition-colors',
            'hover:bg-bg-hover hover:text-text-primary',
          )}
        >
          <Plus className="size-3" aria-hidden="true" />
          Alias
        </button>
      )}
      {term.aliases.length === 0 && !editable ? (
        <span className="text-xs text-text-disabled">None</span>
      ) : null}
    </div>
  );
}
