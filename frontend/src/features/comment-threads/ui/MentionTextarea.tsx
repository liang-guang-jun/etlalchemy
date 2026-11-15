import { useEffect, useRef, useState, type KeyboardEvent } from 'react';

import type { UserSummary } from '@/entities/user';
import { cn } from '@/shared/lib/cn';
import { Textarea } from '@/shared/ui';

import { narrowSuggestions } from '../model/directory';

/** Regex of the mention being typed right before the caret. */
const MENTION_PATTERN = /(?:^|\s)@([\p{L}\p{N}._-]*)$/u;

export interface MentionTextareaProps {
  value: string;
  onChange: (value: string) => void;
  /** Suggestions of the last `@` search; empty hides the list. */
  suggestions: readonly UserSummary[];
  /** Called with the text after the `@` whenever it changes. */
  onQuery: (term: string) => void;
  /** Called when a suggestion is picked, so the caller can keep its name. */
  onPick: (user: UserSummary) => void;
  placeholder?: string;
  rows?: number;
  autoFocus?: boolean;
  disabled?: boolean;
  invalid?: boolean;
  /** Called on `Ctrl`/`Cmd` + `Enter`. */
  onSubmit?: () => void;
}

/**
 * Renders the comment textarea with `@` mention suggestions.
 *
 * A suggestion only replaces the token that is being typed, so the rest of the
 * text — and the body itself — is never rewritten. Mentions are resolved from
 * the text on submit (`resolveMentions`), which keeps them in sync when a token
 * is deleted again.
 *
 * @param props Component props.
 * @returns The textarea with its suggestion list.
 */
export function MentionTextarea({
  value,
  onChange,
  suggestions: candidates,
  onQuery,
  onPick,
  placeholder,
  rows = 3,
  autoFocus = false,
  disabled = false,
  invalid = false,
  onSubmit,
}: MentionTextareaProps) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  const [token, setToken] = useState<{ term: string; start: number; caret: number } | null>(null);
  const [active, setActive] = useState(0);

  const suggestions = token === null ? [] : narrowSuggestions(candidates, token.term);

  useEffect(() => {
    setActive(0);
  }, [token?.term]);

  /**
   * Recomputes the mention token after the text or the caret moved.
   *
   * @param text Current text.
   * @param caret Caret offset the token has to end at.
   */
  const sync = (text: string, caret: number | null): void => {
    if (caret === null) {
      setToken(null);
      onQuery('');
      return;
    }
    const match = MENTION_PATTERN.exec(text.slice(0, caret));
    if (match === null) {
      setToken(null);
      onQuery('');
      return;
    }
    const term = match[1] ?? '';
    setToken({ term, start: caret - term.length - 1, caret });
    onQuery(term);
  };

  /**
   * Replaces the typed token with the picked user's name.
   *
   * @param user User to mention.
   */
  const insert = (user: UserSummary): void => {
    if (token === null) {
      return;
    }
    const name = user.display_name === '' ? user.username : user.display_name;
    const inserted = `@${name} `;
    const next = value.slice(0, token.start) + inserted + value.slice(token.caret);
    onChange(next);
    onPick({ ...user, display_name: name });
    setToken(null);
    onQuery('');
    window.requestAnimationFrame(() => {
      const textarea = ref.current;
      if (textarea === null) {
        return;
      }
      const caret = token.start + inserted.length;
      textarea.focus();
      textarea.setSelectionRange(caret, caret);
    });
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>): void => {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault();
      onSubmit?.();
      return;
    }
    if (token === null || suggestions.length === 0) {
      return;
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive((current) => (current + 1) % suggestions.length);
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive((current) => (current - 1 + suggestions.length) % suggestions.length);
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      setToken(null);
      onQuery('');
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      const user = suggestions[active];
      if (user !== undefined) {
        insert(user);
      }
    }
  };

  return (
    <div className="relative">
      <Textarea
        ref={ref}
        rows={rows}
        value={value}
        disabled={disabled}
        invalid={invalid}
        autoFocus={autoFocus}
        placeholder={placeholder}
        onChange={(event) => {
          onChange(event.target.value);
          sync(event.target.value, event.target.selectionStart);
        }}
        onKeyDown={onKeyDown}
        onClick={(event) => {
          sync(event.currentTarget.value, event.currentTarget.selectionStart);
        }}
        onBlur={() => {
          // The list has to survive the click that picks an entry.
          window.setTimeout(() => {
            setToken(null);
            onQuery('');
          }, 120);
        }}
      />
      {suggestions.length === 0 ? null : (
        <div
          role="listbox"
          aria-label="Mention a user"
          className="absolute inset-x-0 top-full z-10 mt-1 overflow-hidden rounded-md border border-border-base bg-bg-surface shadow-lg"
        >
          {suggestions.map((user, index) => {
            const name = user.display_name === '' ? user.username : user.display_name;
            return (
              <button
                key={user.user_id}
                type="button"
                role="option"
                aria-selected={index === active}
                onMouseDown={(event) => {
                  event.preventDefault();
                }}
                onClick={() => {
                  insert(user);
                }}
                className={cn(
                  'flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm transition-colors',
                  index === active
                    ? 'bg-bg-hover text-text-primary'
                    : 'text-text-secondary hover:bg-bg-hover',
                )}
              >
                <span className="truncate">{name}</span>
                <span className="ml-auto shrink-0 font-mono text-[11px] text-text-disabled">
                  {user.username}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
