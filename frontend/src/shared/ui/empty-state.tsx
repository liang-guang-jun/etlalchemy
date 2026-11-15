import type { ReactNode } from 'react';

import { cn } from '@/shared/lib/cn';

export interface EmptyStateProps {
  title: string;
  description?: string;
  action?: ReactNode;
  icon?: ReactNode;
  /** Drops the frame, for empty states that sit inside an existing panel. */
  plain?: boolean;
  className?: string;
}

/**
 * Renders the empty state of a list or panel.
 *
 * @param props Component props.
 * @returns The empty state element.
 */
export function EmptyState({
  title,
  description,
  action,
  icon,
  plain = false,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-3 px-6 text-center',
        plain
          ? 'bg-transparent py-10'
          : 'rounded-md border border-border-base bg-bg-canvas/40 py-12',
        className,
      )}
    >
      {icon !== undefined ? <div className="text-text-disabled">{icon}</div> : null}
      <p className="text-base font-semibold text-text-primary">{title}</p>
      {description !== undefined ? (
        <p className="max-w-md text-sm text-text-secondary">{description}</p>
      ) : null}
      {action}
    </div>
  );
}
