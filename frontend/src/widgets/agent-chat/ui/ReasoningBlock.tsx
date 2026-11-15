import { BrainCircuit } from 'lucide-react';

import { cn } from '@/shared/lib/cn';

export interface ReasoningBlockProps {
  /** Thinking the model streamed. */
  text: string;
  /** Whether the model is still thinking. */
  streaming?: boolean;
  /** Compact styling of the floating widget. */
  compact?: boolean;
}

/**
 * Renders the thinking that preceded an answer.
 *
 * The text is plain, not markdown: it is a scratchpad, and a model that leaves a
 * half-written fence in it must not break the layout of the page.
 *
 * @param props Component props.
 * @returns The thinking block, or `null` when the model did not think out loud.
 */
export function ReasoningBlock({ text, streaming = false, compact = false }: ReasoningBlockProps) {
  if (text === '') {
    return null;
  }
  return (
    <div className={cn('flex gap-2 text-text-secondary', compact ? 'text-[11px]' : 'text-xs')}>
      <BrainCircuit className="mt-0.5 size-3.5 shrink-0 text-text-disabled" aria-hidden="true" />
      <p className="min-w-0 italic whitespace-pre-wrap">
        {text}
        {streaming ? (
          <span
            aria-label="The model is still thinking"
            className="ml-1 inline-block h-3.5 w-1.5 animate-pulse bg-text-disabled align-middle"
          />
        ) : null}
      </p>
    </div>
  );
}
