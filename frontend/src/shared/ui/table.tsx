import type { HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from 'react';

import { cn } from '@/shared/lib/cn';

/**
 * Renders the scroll container and table element.
 *
 * @param props Component props.
 * @returns The table element.
 */
export function Table({ className, ...rest }: HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="w-full overflow-x-auto rounded-md border border-border-base bg-bg-surface">
      <table className={cn('w-full border-collapse text-sm', className)} {...rest} />
    </div>
  );
}

/**
 * Renders a table header row group.
 *
 * @param props Component props.
 * @returns The header element.
 */
export function TableHead({ className, ...rest }: HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <thead
      className={cn('border-b border-border-base bg-bg-canvas text-text-secondary', className)}
      {...rest}
    />
  );
}

/**
 * Renders a table body.
 *
 * @param props Component props.
 * @returns The body element.
 */
export function TableBody({ className, ...rest }: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn('divide-y divide-border-base', className)} {...rest} />;
}

/**
 * Renders a table row.
 *
 * @param props Component props.
 * @returns The row element.
 */
export function TableRow({ className, ...rest }: HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr className={cn('group/row transition-colors hover:bg-bg-hover', className)} {...rest} />
  );
}

/**
 * Renders a header cell.
 *
 * @param props Component props.
 * @returns The header cell element.
 */
export function TableHeaderCell({ className, ...rest }: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      scope="col"
      className={cn('px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide', className)}
      {...rest}
    />
  );
}

/**
 * Renders a body cell.
 *
 * @param props Component props.
 * @returns The body cell element.
 */
export function TableCell({ className, ...rest }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn('px-4 py-3 align-middle text-text-primary', className)} {...rest} />;
}
