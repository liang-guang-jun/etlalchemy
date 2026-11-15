import type { Ref, TextareaHTMLAttributes } from 'react';

import { cn } from '@/shared/lib/cn';

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  invalid?: boolean;
  /** Element ref, used to restore the caret after an insertion. */
  ref?: Ref<HTMLTextAreaElement>;
}

/**
 * Renders a multi-line text input.
 *
 * @param props Component props.
 * @returns The textarea element.
 */
export function Textarea({ className, invalid = false, rows = 4, ref, ...rest }: TextareaProps) {
  return (
    <textarea
      ref={ref}
      rows={rows}
      aria-invalid={invalid}
      className={cn(
        'w-full rounded-md border border-border-strong bg-bg-surface px-3 py-2 text-sm text-text-primary',
        'placeholder:text-text-disabled focus:border-brand focus:outline-none',
        'disabled:bg-bg-canvas',
        invalid && 'border-danger focus:border-danger',
        className,
      )}
      {...rest}
    />
  );
}
