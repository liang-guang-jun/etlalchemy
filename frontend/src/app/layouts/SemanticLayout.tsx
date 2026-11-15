import { AnimatePresence, motion } from 'motion/react';
import { useLocation, useOutlet } from 'react-router';

/**
 * Frame of the semantic model gallery: one full-width scrolling surface whose
 * pages fade in, so the gallery and a workspace feel like two depths of the
 * same stack.
 *
 * @returns The model gallery layout.
 */
export function SemanticLayout() {
  const location = useLocation();
  const outlet = useOutlet();

  return (
    <div className="h-full overflow-y-auto bg-bg-surface">
      <div className="mx-auto w-full max-w-6xl p-8">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
          >
            {outlet}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}
