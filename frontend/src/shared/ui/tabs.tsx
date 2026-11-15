import { motion } from 'motion/react';
import { useId } from 'react';

import { cn } from '@/shared/lib/cn';

export interface TabItem {
  value: string;
  label: string;
  count?: number;
  disabled?: boolean;
}

export interface TabsProps {
  items: TabItem[];
  value: string;
  onChange: (value: string) => void;
  className?: string;
}

/**
 * Renders a controlled tab bar with a sliding brand-coloured indicator.
 *
 * @param props Component props.
 * @returns The tab list element.
 */
export function Tabs({ items, value, onChange, className }: TabsProps) {
  const indicatorId = useId();

  return (
    <div role="tablist" className={cn('flex gap-1 border-b border-border-base', className)}>
      {items.map((item) => {
        const selected = item.value === value;
        return (
          <button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={selected}
            disabled={item.disabled === true}
            onClick={() => {
              onChange(item.value);
            }}
            className={cn(
              'relative -mb-px flex h-10 items-center gap-1 rounded-t-sm px-3 text-sm transition-colors',
              selected
                ? 'font-semibold text-text-primary'
                : 'text-text-secondary hover:text-text-primary',
              item.disabled === true && 'cursor-not-allowed text-text-disabled',
            )}
          >
            <span className="relative">{item.label}</span>
            {item.count !== undefined ? (
              <span className="text-xs text-text-secondary">({item.count})</span>
            ) : null}
            {selected ? (
              <motion.span
                layoutId={`tab-indicator-${indicatorId}`}
                aria-hidden="true"
                className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-brand"
                transition={{ type: 'spring', stiffness: 400, damping: 35 }}
              />
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
