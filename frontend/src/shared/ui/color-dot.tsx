import { cn } from '@/shared/lib/cn';

export interface ColorDotProps {
  /** Colour as `#rrggbb`; an empty string renders a hollow ring. */
  color: string;
  /** Extra classes, typically the size. */
  className?: string;
  /** Optional accessible description; the dot is decorative otherwise. */
  title?: string;
}

/**
 * Renders the small round colour indicator used for terms.
 *
 * @param props Component props.
 * @returns The colour dot.
 */
export function ColorDot({ color, className, title }: ColorDotProps) {
  return (
    <span
      aria-hidden={title === undefined ? true : undefined}
      title={title}
      className={cn(
        'inline-block size-3 shrink-0 rounded-full border',
        color === '' ? 'border-border-strong bg-transparent' : 'border-black/10',
        className,
      )}
      style={color === '' ? undefined : { backgroundColor: color }}
    />
  );
}
