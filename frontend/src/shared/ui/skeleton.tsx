import { cn } from '@/shared/lib/cn';

export interface SkeletonProps {
  className?: string;
  lines?: number;
}

/**
 * Renders a loading placeholder.
 *
 * @param props Component props.
 * @returns The skeleton element(s).
 */
export function Skeleton({ className, lines = 1 }: SkeletonProps) {
  return (
    <div className="space-y-2" aria-hidden="true">
      {Array.from({ length: lines }, (_, index) => (
        <div key={index} className={cn('h-4 animate-pulse rounded-sm bg-bg-canvas', className)} />
      ))}
    </div>
  );
}
