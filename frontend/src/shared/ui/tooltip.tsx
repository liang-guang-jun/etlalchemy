import type { ReactNode } from 'react';

import { cn } from '@/shared/lib/cn';

export interface TooltipProps {
  content: string;
  children: ReactNode;
  side?: 'top' | 'bottom';
  className?: string;
}

/**
 * Renders a hover/focus tooltip around its child.
 *
 * @param props Component props.
 * @returns The wrapped element with the tooltip bubble.
 */
export function Tooltip({ content, children, side = 'top', className }: TooltipProps) {
  return (
    <span className={cn('group relative inline-flex', className)}>
      {children}
      <span
        role="tooltip"
        className={cn(
          'pointer-events-none absolute left-1/2 z-50 hidden -translate-x-1/2 whitespace-nowrap',
          'rounded-sm bg-text-primary px-2 py-1 text-xs text-bg-surface shadow-sm',
          'group-hover:block group-focus-within:block',
          side === 'top' ? 'bottom-full mb-1' : 'top-full mt-1',
        )}
      >
        {content}
      </span>
    </span>
  );
}
