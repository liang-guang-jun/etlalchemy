import { AlertTriangle } from 'lucide-react';

import { cn } from '@/shared/lib/cn';
import { Button } from './button';

export interface ErrorStateProps {
  title?: string;
  detail?: string;
  onRetry?: () => void;
  className?: string;
}

/**
 * Renders a failed-request state with an optional retry action.
 *
 * @param props Component props.
 * @returns The error state element.
 */
export function ErrorState({
  title = 'Failed to load',
  detail,
  onRetry,
  className,
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={cn(
        'flex flex-col items-center justify-center gap-2 rounded-md border border-danger/30 bg-bg-surface px-6 py-10 text-center',
        className,
      )}
    >
      <AlertTriangle className="size-5 text-danger" aria-hidden="true" />
      <p className="text-sm font-semibold text-text-primary">{title}</p>
      {detail !== undefined ? <p className="text-sm text-text-secondary">{detail}</p> : null}
      {onRetry !== undefined ? (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}
