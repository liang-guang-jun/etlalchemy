import type { SelectHTMLAttributes } from 'react';

import { cn } from '@/shared/lib/cn';

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'children'> {
  options: SelectOption[];
  placeholder?: string;
  invalid?: boolean;
}

/**
 * Renders a native select with the shared styling.
 *
 * @param props Component props.
 * @returns The select element.
 */
export function Select({ options, placeholder, className, invalid = false, ...rest }: SelectProps) {
  return (
    <select
      aria-invalid={invalid}
      className={cn(
        'h-9 w-full rounded-md border border-border-strong bg-bg-surface px-3 text-sm text-text-primary',
        'focus:border-brand focus:outline-none disabled:bg-bg-canvas disabled:text-text-disabled',
        invalid && 'border-danger focus:border-danger',
        className,
      )}
      {...rest}
    >
      {placeholder !== undefined ? <option value="">{placeholder}</option> : null}
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}
