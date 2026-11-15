import { AnimatePresence, motion } from 'motion/react';
import { CheckCircle2, Info, X, XCircle } from 'lucide-react';

import { cn } from '@/shared/lib/cn';
import { useToastStore, type ToastKind } from './toast-store';

const ICONS = {
  success: CheckCircle2,
  error: XCircle,
  info: Info,
} as const;

const TONE_CLASSES: Record<ToastKind, string> = {
  success: 'border-success/40 text-success',
  error: 'border-danger/40 text-danger',
  info: 'border-border-strong text-text-secondary',
};

/**
 * Renders the stack of active toasts.
 *
 * @returns The toast viewport.
 */
export function Toaster() {
  const items = useToastStore((state) => state.items);
  const dismiss = useToastStore((state) => state.dismiss);

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-4 z-[100] flex flex-col items-center gap-2">
      <AnimatePresence initial={false}>
        {items.map((item) => {
          const Icon = ICONS[item.kind];
          return (
            <motion.div
              key={item.id}
              layout
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 8 }}
              className={cn(
                'pointer-events-auto flex w-[min(28rem,calc(100vw-2rem))] items-start gap-2 rounded-md border bg-bg-surface px-3 py-2 shadow-sm',
                TONE_CLASSES[item.kind],
              )}
              role="status"
            >
              <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <p className="flex-1 text-sm text-text-primary">{item.message}</p>
              <button
                type="button"
                aria-label="Dismiss notification"
                className="text-text-secondary hover:text-text-primary"
                onClick={() => {
                  dismiss(item.id);
                }}
              >
                <X className="size-4" aria-hidden="true" />
              </button>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
