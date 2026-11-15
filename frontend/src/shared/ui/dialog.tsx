import { useEffect, type ReactNode } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { X } from 'lucide-react';

import { cn } from '@/shared/lib/cn';

export interface DialogProps {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  children?: ReactNode;
  footer?: ReactNode;
  size?: 'sm' | 'md' | 'lg';
}

const SIZE_CLASSES: Record<NonNullable<DialogProps['size']>, string> = {
  sm: 'max-w-sm',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
};

/**
 * Renders a modal dialog.
 *
 * @param props Component props.
 * @returns The dialog overlay, or `null` while closed.
 */
export function Dialog({
  open,
  title,
  description,
  onClose,
  children,
  footer,
  size = 'md',
}: DialogProps) {
  useEffect(() => {
    if (!open) {
      return undefined;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
        >
          <motion.div
            className="absolute inset-0 bg-black/20 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.div
            className={cn(
              'relative flex max-h-[calc(100vh-2rem)] w-full flex-col rounded-lg border',
              'border-border-base bg-bg-surface shadow-xl',
              SIZE_CLASSES[size],
            )}
            initial={{ opacity: 0, y: 8, scale: 0.99 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.99 }}
          >
            <header className="flex shrink-0 items-start justify-between gap-3 border-b border-border-base p-4">
              <div>
                <h2 className="text-base font-semibold text-text-primary">{title}</h2>
                {description !== undefined ? (
                  <p className="mt-1 text-sm text-text-secondary">{description}</p>
                ) : null}
              </div>
              <button
                type="button"
                aria-label="Close"
                className="text-text-secondary hover:text-text-primary"
                onClick={onClose}
              >
                <X className="size-4" aria-hidden="true" />
              </button>
            </header>
            {children !== undefined ? (
              <div className="min-h-0 flex-1 overflow-y-auto p-6">{children}</div>
            ) : null}
            {footer !== undefined ? (
              <footer className="flex shrink-0 justify-end gap-2 border-t border-border-base p-4">
                {footer}
              </footer>
            ) : null}
          </motion.div>
        </div>
      ) : null}
    </AnimatePresence>
  );
}
