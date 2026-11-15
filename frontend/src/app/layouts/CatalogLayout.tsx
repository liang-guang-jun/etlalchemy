import { AnimatePresence, motion } from 'motion/react';
import { useLocation, useOutlet } from 'react-router';

import { CatalogExplorer } from '@/widgets/catalog-explorer';

/**
 * Split layout of the data catalog workspace: a persistent resource tree on the
 * left and the selected node's detail panel on the right.
 *
 * The tree lives in this layout so that navigation between nodes never remounts
 * it and keeps its expansion state.
 *
 * @returns The catalog workspace layout.
 */
export function CatalogLayout() {
  const location = useLocation();
  const outlet = useOutlet();

  return (
    <div className="flex h-full min-h-0">
      <aside className="flex w-80 shrink-0 flex-col border-r border-border-base bg-bg-surface">
        <CatalogExplorer />
      </aside>

      <div className="min-w-0 flex-1 overflow-y-auto bg-bg-surface">
        <div className="mx-auto w-full max-w-5xl p-8">
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
    </div>
  );
}
