import { motion } from 'motion/react';
import type { ReactNode } from 'react';

import { cn } from '@/shared/lib/cn';
import { Tooltip } from './tooltip';

export interface ActionIconButtonProps {
  /** Accessible name and tooltip text. */
  label: string;
  /** Usually a Lucide icon rendered at `size-4`. */
  icon: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  /** `danger` turns the hover state red, used by destructive actions. */
  tone?: 'default' | 'danger';
  className?: string;
}

/**
 * Renders an icon-only action with a tooltip and a physical press animation.
 *
 * @param props Component props.
 * @returns The icon button.
 */
export function ActionIconButton({
  label,
  icon,
  onClick,
  disabled = false,
  tone = 'default',
  className,
}: ActionIconButtonProps) {
  return (
    <Tooltip content={label}>
      <motion.button
        type="button"
        aria-label={label}
        disabled={disabled}
        onClick={onClick}
        whileHover={disabled ? undefined : { scale: 1.1 }}
        whileTap={disabled ? undefined : { scale: 0.9 }}
        transition={{ type: 'spring', stiffness: 400, damping: 22 }}
        className={cn(
          'inline-flex size-8 items-center justify-center rounded-md text-text-secondary transition-colors',
          'hover:bg-bg-hover hover:text-text-primary',
          'disabled:cursor-not-allowed disabled:text-text-disabled disabled:hover:bg-transparent',
          'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand',
          tone === 'danger' && 'hover:bg-danger/10 hover:text-danger',
          className,
        )}
      >
        {icon}
      </motion.button>
    </Tooltip>
  );
}

/**
 * Renders the thin separator that isolates destructive actions in an icon group.
 *
 * @returns The separator element.
 */
export function ActionIconDivider() {
  return <span className="mx-1 h-4 w-px bg-border-base" aria-hidden="true" />;
}
