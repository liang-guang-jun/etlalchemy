import type { ReactNode } from 'react';

import { cn } from '@/shared/lib/cn';

export interface PageContainerProps {
  children: ReactNode;
  className?: string;
}

/**
 * Scroll container of a routed page: full height, comfortable padding and a
 * centred column that stops growing on very wide screens.
 *
 * @param props Component props.
 * @returns The page container.
 */
export function PageContainer({ children, className }: PageContainerProps) {
  return (
    <div className={cn('h-full overflow-y-auto p-8', className)}>
      <div className="mx-auto w-full max-w-7xl">{children}</div>
    </div>
  );
}
