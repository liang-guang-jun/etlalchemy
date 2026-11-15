import { useEffect, type ReactNode } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { X } from 'lucide-react';

import { cn } from '@/shared/lib/cn';

export interface DrawerProps {
  open: boolean;
  /** Title of the panel; accepts a node so the caller can put a link in it. */
  title: ReactNode;
  onClose: () => void;
  children?: ReactNode;
  footer?: ReactNode;
  width?: 'md' | 'lg';
}

const WIDTH_CLASSES: Record<NonNullable<DrawerProps['width']>, string> = {
  md: 'max-w-md',
  lg: 'max-w-xl',
};

/**
 * Renders a right-hand side panel.
 *
 * @param props Component props.
 * @returns The drawer overlay, or `null` while closed.
 */
export function Drawer({ open, title, onClose, children, footer, width = 'md' }: DrawerProps) {
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
        <div className="fixed inset-0 z-50" role="dialog" aria-modal="true">
          <motion.div
            className="absolute inset-0 bg-black/20 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.aside
            className={cn(
              'absolute inset-y-0 right-0 flex w-full flex-col rounded-l-lg border-l border-border-base bg-bg-surface shadow-xl',
              WIDTH_CLASSES[width],
            )}
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
          >
            <header className="flex items-center justify-between gap-3 border-b border-border-base px-5 py-3">
              <h2 className="text-base font-semibold text-text-primary">{title}</h2>
              <button
                type="button"
                aria-label="Close"
                className="text-text-secondary hover:text-text-primary"
                onClick={onClose}
              >
                <X className="size-4" aria-hidden="true" />
              </button>
            </header>
            <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
            {footer !== undefined ? (
              <footer className="flex justify-end gap-2 border-t border-border-base px-5 py-3">
                {footer}
              </footer>
            ) : null}
          </motion.aside>
        </div>
      ) : null}
    </AnimatePresence>
  );
}
