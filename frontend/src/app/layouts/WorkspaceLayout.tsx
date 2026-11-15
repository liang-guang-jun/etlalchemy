import { AnimatePresence, motion } from 'motion/react';
import { useLocation, useOutlet } from 'react-router';

/**
 * Frame of a fixed-height workspace page: the outlet fills the card instead of
 * growing it, so a page can split itself into panes that scroll internally.
 *
 * Unlike `IngestionLayout`, this frame never scrolls as a whole. Every child
 * therefore gets a definite height, which is what a `h-full` / `min-h-0`
 * percentage chain needs to turn `overflow-y-auto` into a real scroller.
 *
 * @returns The workspace layout.
 */
export function WorkspaceLayout() {
  const location = useLocation();
  const outlet = useOutlet();

  return (
    <div className="h-full overflow-hidden bg-bg-surface">
      <div className="mx-auto flex h-full min-h-0 w-full max-w-6xl flex-col p-8">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            className="flex min-h-0 flex-1 flex-col"
          >
            {outlet}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}
