import { cn } from '@/shared/lib/cn';

export interface BrandProps {
  className?: string;
}

/**
 * Flat typographic wordmark: a forward-leaning lockup at 20px where only the
 * `A` carries the brand accent. Everything else is the theme's primary text
 * colour, so the mark follows light and dark mode without a hard-coded black.
 *
 * The mark is deliberately static; hovering only fades it slightly.
 *
 * @param props Component props.
 * @returns The brand element.
 */
export function Brand({ className }: BrandProps) {
  return (
    <span
      className={cn(
        'group/brand flex cursor-pointer select-none items-center transition-opacity duration-200 hover:opacity-80',
        className,
      )}
    >
      <span className="-skew-x-6 whitespace-nowrap text-xl leading-none">
        {/* <span className="font-black tracking-tighter text-text-primary">ETL</span> */}
        <span className="ml-0.5 font-bold tracking-tight text-text-primary">
          <span className="text-brand-ink">ETLA</span>lchemy
        </span>
      </span>
    </span>
  );
}
