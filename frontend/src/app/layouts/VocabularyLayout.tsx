import { motion } from 'motion/react';
import { Outlet, useLocation } from 'react-router';

import { TermExplorer } from '@/widgets/term-explorer';

/**
 * Split layout of the business-terms workspace: a persistent domain and term
 * tree on the left and the selected node's detail panel on the right.
 *
 * The tree lives in this layout so that navigation between nodes never remounts
 * it and keeps its expansion state.
 *
 * @returns The vocabulary workspace layout.
 */
export function VocabularyLayout() {
  const location = useLocation();

  return (
    <div className="flex h-full min-h-0">
      <aside className="flex w-80 shrink-0 flex-col border-r border-border-base bg-bg-surface">
        <TermExplorer />
      </aside>

      <div className="min-w-0 flex-1 overflow-y-auto bg-bg-surface">
        <div className="mx-auto w-full max-w-5xl p-8">
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
          >
            <Outlet />
          </motion.div>
        </div>
      </div>
    </div>
  );
}
