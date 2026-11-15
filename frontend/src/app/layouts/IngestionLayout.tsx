import { AnimatePresence, motion } from 'motion/react';
import { useLocation, useOutlet } from 'react-router';

/**
 * Frame of the ingestion workspace: one scrolling surface whose pages slide in
 * from the right, so the connections list and a connection detail feel like two
 * depths of the same stack.
 *
 * @returns The ingestion layout.
 */
export function IngestionLayout() {
  const location = useLocation();
  const outlet = useOutlet();

  return (
    <div className="h-full overflow-y-auto bg-bg-surface">
      <div className="mx-auto w-full max-w-6xl p-8">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            className="h-full"
          >
            {outlet}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}
