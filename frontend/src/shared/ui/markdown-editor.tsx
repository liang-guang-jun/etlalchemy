import { useEffect, useRef, useState } from 'react';
import {
  Bold,
  Code2,
  Heading2,
  Italic,
  Link2,
  List,
  ListOrdered,
  Pencil,
  Quote,
} from 'lucide-react';

import { cn } from '@/shared/lib/cn';
import { Button } from './button';
import { Markdown } from './markdown';

export interface MarkdownEditorProps {
  /** Current markdown source. */
  value: string;
  /** Called with the edited source when the editor commits. */
  onSave: (value: string) => void;
  /** Whether the value may be edited at all. */
  editable?: boolean;
  /** Disables the commit buttons while a request is in flight. */
  saving?: boolean;
  /** Shown while the value is empty. */
  placeholder?: string;
  /** Accessible name of the editable region. */
  label?: string;
  className?: string;
}

interface ToolbarAction {
  label: string;
  icon: typeof Bold;
  apply: (selection: string) => { before: string; after: string };
}

const ACTIONS: ToolbarAction[] = [
  { label: 'Bold', icon: Bold, apply: () => ({ before: '**', after: '**' }) },
  { label: 'Italic', icon: Italic, apply: () => ({ before: '_', after: '_' }) },
  { label: 'Heading', icon: Heading2, apply: () => ({ before: '## ', after: '' }) },
  { label: 'Inline code', icon: Code2, apply: () => ({ before: '`', after: '`' }) },
  { label: 'Link', icon: Link2, apply: () => ({ before: '[', after: '](https://)' }) },
  { label: 'Bullet list', icon: List, apply: () => ({ before: '- ', after: '' }) },
  { label: 'Numbered list', icon: ListOrdered, apply: () => ({ before: '1. ', after: '' }) },
  { label: 'Quote', icon: Quote, apply: () => ({ before: '> ', after: '' }) },
];

/**
 * Renders markdown and switches to an inline editor with a formatting toolbar.
 *
 * The rendered view is the default; clicking the content or the edit icon opens
 * the editor, and leaving the block (or pressing Save) commits the new source.
 *
 * @param props Component props.
 * @returns The markdown block.
 */
export function MarkdownEditor({
  value,
  onSave,
  editable = false,
  saving = false,
  placeholder = 'Write the definition in markdown.',
  label = 'Definition',
  className,
}: MarkdownEditorProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    // A new source from the server always wins; the local draft only bridges
    // the gap between a commit and the eventual read-model refresh.
    setDraft(value);
  }, [value]);

  useEffect(() => {
    if (editing) {
      textareaRef.current?.focus();
    }
  }, [editing]);

  const commit = () => {
    if (!editing) {
      return;
    }
    setEditing(false);
    const next = draft.trim();
    if (next !== value.trim()) {
      onSave(next);
    }
  };

  const cancel = () => {
    setDraft(value);
    setEditing(false);
  };

  const applyAction = (action: ToolbarAction) => {
    const textarea = textareaRef.current;
    if (textarea === null) {
      return;
    }
    const { selectionStart, selectionEnd } = textarea;
    const selection = draft.slice(selectionStart, selectionEnd);
    const { before, after } = action.apply(selection);
    const next =
      draft.slice(0, selectionStart) + before + selection + after + draft.slice(selectionEnd);
    setDraft(next);
    const caret = selectionStart + before.length + selection.length;
    requestAnimationFrame(() => {
      textarea.focus();
      textarea.setSelectionRange(caret, caret);
    });
  };

  return (
    <div
      className={cn(
        'group/definition relative rounded-lg transition-colors',
        editing
          ? 'border border-border-strong bg-bg-surface shadow-sm'
          : editable
            ? 'cursor-text border border-border-base bg-bg-hover-subtle/50 hover:border-border-strong'
            : 'border border-border-base bg-bg-hover-subtle/50',
        className,
      )}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          commit();
        }
      }}
    >
      {editing ? (
        <div className="flex flex-col">
          <div
            role="toolbar"
            aria-label="Markdown formatting"
            className="flex flex-wrap items-center gap-0.5 border-b border-border-base px-1 py-1"
          >
            {ACTIONS.map((action) => (
              <button
                key={action.label}
                type="button"
                aria-label={action.label}
                title={action.label}
                // Keeping the focus in the textarea prevents a blur-commit per click.
                onMouseDown={(event) => {
                  event.preventDefault();
                }}
                onClick={() => {
                  applyAction(action);
                }}
                className="flex size-7 items-center justify-center rounded-sm text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
              >
                <action.icon className="size-3.5" aria-hidden="true" />
              </button>
            ))}
            <span className="ml-auto pr-1 text-[11px] text-text-disabled">Markdown</span>
          </div>
          <textarea
            ref={textareaRef}
            aria-label={label}
            value={draft}
            placeholder={placeholder}
            spellCheck
            onChange={(event) => {
              setDraft(event.target.value);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                event.preventDefault();
                cancel();
                return;
              }
              if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                commit();
              }
            }}
            rows={Math.min(20, Math.max(6, draft.split('\n').length + 1))}
            className="max-h-80 min-h-32 w-full resize-y bg-transparent px-3 py-2 font-mono text-sm text-text-primary outline-none placeholder:text-text-disabled"
          />
          <div className="flex items-center justify-end gap-2 border-t border-border-base px-2 py-1.5">
            <span className="mr-auto pl-1 text-[11px] text-text-disabled">
              Esc cancels · Ctrl/⌘ + Enter saves
            </span>
            <Button size="sm" variant="ghost" onClick={cancel}>
              Cancel
            </Button>
            <Button size="sm" loading={saving} onClick={commit}>
              Save
            </Button>
          </div>
        </div>
      ) : (
        <div className={cn('relative min-h-24 px-5 py-4', editable && 'pr-12')}>
          {draft.trim() === '' ? (
            <p className="text-sm text-text-disabled">{placeholder}</p>
          ) : (
            <Markdown>{draft}</Markdown>
          )}
          {editable ? (
            <>
              <button
                type="button"
                aria-label={`Edit ${label.toLowerCase()} content`}
                tabIndex={-1}
                onClick={() => {
                  setEditing(true);
                }}
                className="absolute inset-0 cursor-text rounded-lg"
              />
              <button
                type="button"
                aria-label={`Edit ${label.toLowerCase()}`}
                title="Edit"
                onClick={() => {
                  setEditing(true);
                }}
                className="absolute top-2 right-2 z-10 flex size-7 items-center justify-center rounded-sm bg-bg-surface text-text-secondary opacity-60 transition-opacity hover:bg-bg-hover hover:text-text-primary hover:opacity-100 focus-visible:opacity-100"
              >
                <Pencil className="size-3.5" aria-hidden="true" />
              </button>
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}
