import { AnimatePresence, motion } from 'motion/react';
import type { ReactNode } from 'react';

import { cn } from '@/shared/lib/cn';
import { Tabs, type TabItem } from './tabs';

const STAGGER = {
  hidden: {},
  show: { transition: { staggerChildren: 0.05, delayChildren: 0.02 } },
};

const FROM_LEFT = {
  hidden: { opacity: 0, x: -8 },
  show: { opacity: 1, x: 0 },
};

const FROM_RIGHT = {
  hidden: { opacity: 0, x: 8 },
  show: { opacity: 1, x: 0 },
};

export interface ResourceDetailLayoutProps {
  /** Breadcrumb trail of the page. */
  breadcrumbs: ReactNode;
  title: string;
  description?: string;
  /** Badges describing the resource, e.g. its type or size. */
  meta?: ReactNode;
  /** Right aligned action group, usually `ActionIconButton`s. */
  actions?: ReactNode;
  /** Tab definitions; omit for pages without tabs. */
  tabs?: TabItem[];
  /** Selected tab value, required when `tabs` is set. */
  tab?: string;
  onTabChange?: (value: string) => void;
  /** Sections rendered below the title block, inside the animated panel. */
  children?: ReactNode;
  className?: string;
}

/**
 * Renders the shared detail skeleton of the catalog pages: a staggered summary
 * header, animated tabs and one surface holding the tab content.
 *
 * @param props Component props.
 * @returns The detail layout.
 */
export function ResourceDetailLayout({
  breadcrumbs,
  title,
  description,
  meta,
  actions,
  tabs,
  tab,
  onTabChange,
  children,
  className,
}: ResourceDetailLayoutProps) {
  const active = tab ?? tabs?.[0]?.value ?? '';

  return (
    <div className={cn('w-full', className)}>
      <motion.header
        initial="hidden"
        animate="show"
        variants={STAGGER}
        className="mb-6 flex flex-col gap-3"
      >
        <motion.div variants={FROM_LEFT} className="min-w-0 text-sm">
          {breadcrumbs}
        </motion.div>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-2">
            <motion.h1
              variants={FROM_LEFT}
              className="text-2xl leading-tight font-bold tracking-tight text-text-primary"
            >
              {title}
            </motion.h1>
            {description === undefined || description === '' ? null : (
              <motion.p variants={FROM_LEFT} className="text-sm text-text-secondary">
                {description}
              </motion.p>
            )}{' '}
            {meta === undefined ? null : (
              <motion.div variants={FROM_LEFT} className="flex flex-wrap items-center gap-2">
                {meta}
              </motion.div>
            )}
          </div>
          {actions === undefined ? null : (
            <motion.div variants={FROM_RIGHT} className="flex shrink-0 items-center gap-0.5">
              {actions}
            </motion.div>
          )}
        </div>
      </motion.header>

      {tabs === undefined ? (
        <div className="rounded-lg border border-border-base bg-bg-canvas/40 p-4">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={active}
              initial={{ opacity: 0, x: 10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -10 }}
              transition={{ duration: 0.18, ease: 'easeOut' }}
            >
              {children}
            </motion.div>
          </AnimatePresence>
        </div>
      ) : (
        <>
          <Tabs items={tabs} value={active} onChange={onTabChange ?? (() => {})} />
          <div className="mt-3 rounded-lg border border-border-base bg-bg-canvas/40 p-4">
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={active}
                initial={{ opacity: 0, x: 10 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -10 }}
                transition={{ duration: 0.18, ease: 'easeOut' }}
              >
                {children}
              </motion.div>
            </AnimatePresence>
          </div>
        </>
      )}
    </div>
  );
}
