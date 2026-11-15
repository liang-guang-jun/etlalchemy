import type { ReactNode } from 'react';

import { cn } from '@/shared/lib/cn';

export interface PageHeaderProps {
  title: string;
  description?: string;
  actions?: ReactNode;
  breadcrumb?: ReactNode;
  className?: string;
}

/**
 * Renders the title block of a page.
 *
 * @param props Component props.
 * @returns The page header element.
 */
export function PageHeader({
  title,
  description,
  actions,
  breadcrumb,
  className,
}: PageHeaderProps) {
  return (
    <header className={cn('mb-8 flex flex-col gap-2', className)}>
      {breadcrumb !== undefined ? (
        <div className="text-xs text-text-secondary">{breadcrumb}</div>
      ) : null}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-text-primary">{title}</h1>
          {description !== undefined ? (
            <p className="mt-1 text-sm text-text-secondary">{description}</p>
          ) : null}
        </div>
        {actions !== undefined ? <div className="flex items-center gap-2">{actions}</div> : null}
      </div>
    </header>
  );
}
