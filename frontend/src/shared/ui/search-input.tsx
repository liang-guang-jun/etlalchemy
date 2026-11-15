import { Search } from 'lucide-react';

import { cn } from '@/shared/lib/cn';

export interface SearchInputProps {
  value: string;
  onChange: (value: string) => void;
  /** Accessible name of the input. */
  ariaLabel: string;
  placeholder?: string;
  className?: string;
}

/**
 * Renders the compact search field used above the catalog lists.
 *
 * @param props Component props.
 * @returns The search input.
 */
export function SearchInput({
  value,
  onChange,
  ariaLabel,
  placeholder,
  className,
}: SearchInputProps) {
  return (
    <div className={cn('relative', className)}>
      <Search
        className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-text-secondary"
        aria-hidden="true"
      />
      <input
        type="search"
        aria-label={ariaLabel}
        placeholder={placeholder}
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        className="h-8 w-64 rounded-md border border-border-strong bg-bg-canvas pr-2 pl-7 text-sm text-text-primary transition-colors outline-none placeholder:text-text-disabled focus:border-brand"
      />
    </div>
  );
}
