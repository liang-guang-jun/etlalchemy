import type { ButtonHTMLAttributes, ReactNode } from 'react';

import { cn } from '@/shared/lib/cn';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'danger-ghost';
export type ButtonSize = 'sm' | 'md';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: ReactNode;
}

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: 'bg-brand text-brand-text hover:bg-brand-hover disabled:opacity-50',
  secondary:
    'border border-transparent bg-transparent text-text-secondary hover:border-border-base hover:bg-bg-hover hover:text-text-primary disabled:text-text-disabled',
  ghost:
    'bg-transparent text-text-secondary hover:bg-bg-hover hover:text-text-primary disabled:text-text-disabled',
  danger: 'bg-danger text-white hover:bg-danger/90 disabled:opacity-50',
  'danger-ghost':
    'border border-transparent bg-transparent text-text-secondary hover:border-danger/30 hover:bg-danger/10 hover:text-danger disabled:text-text-disabled',
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: 'h-8 gap-1.5 px-3 text-xs',
  md: 'h-9 gap-2 px-4 text-sm',
};

/**
 * Renders a button with the shared variants.
 *
 * @param props Component props.
 * @returns The button element.
 */
export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  icon,
  className,
  disabled,
  children,
  type = 'button',
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled === true || loading}
      className={cn(
        'inline-flex cursor-pointer items-center justify-center rounded-md font-medium transition-colors',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand',
        'disabled:cursor-not-allowed',
        VARIANT_CLASSES[variant],
        SIZE_CLASSES[size],
        className,
      )}
      {...rest}
    >
      {loading ? (
        <span className="size-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
      ) : (
        icon
      )}
      {children}
    </button>
  );
}
