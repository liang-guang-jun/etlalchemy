import type { InputHTMLAttributes } from 'react';

import { cn } from '@/shared/lib/cn';

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  invalid?: boolean;
}

/**
 * Renders a single-line text input.
 *
 * @param props Component props.
 * @returns The input element.
 */
export function Input({ className, invalid = false, ...rest }: InputProps) {
  return (
    <input
      aria-invalid={invalid}
      className={cn(
        'h-9 w-full rounded-md border border-border-strong bg-bg-surface px-3 text-sm text-text-primary',
        'placeholder:text-text-disabled focus:border-brand focus:outline-none',
        'disabled:bg-bg-canvas disabled:text-text-disabled',
        invalid && 'border-danger focus:border-danger',
        className,
      )}
      {...rest}
    />
  );
}
