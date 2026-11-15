import type { ReactNode } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { ChevronRight } from 'lucide-react';

import { describeSteps, type AgentMessage } from '@/entities/agent';
import { cn } from '@/shared/lib/cn';

export interface StepsCollapseProps {
  /** Message whose steps are folded. */
  message: AgentMessage;
  /** Whether the steps are currently folded away. */
  collapsed: boolean;
  /** Called by the summary to fold or unfold the steps. */
  onToggle: () => void;
  /** Compact styling of the floating widget. */
  compact?: boolean;
  /** The thinking and the tool cards. */
  children: ReactNode;
}

/**
 * Renders the foldable trace of one assistant message.
 *
 * The trace stays open while the run writes, so the thinking and the tool calls
 * can be followed as they happen; it folds once the final answer is complete,
 * because it is context for the answer rather than the answer. The summary
 * stays clickable, so the reader can open it again.
 *
 * @param props Component props.
 * @returns The summary and, when unfolded, the steps.
 */
export function StepsCollapse({
  message,
  collapsed,
  onToggle,
  compact = false,
  children,
}: StepsCollapseProps) {
  return (
    <div className={cn('mb-2', compact ? 'text-[11px]' : 'text-xs')}>
      <button
        type="button"
        aria-expanded={!collapsed}
        className="flex w-full items-center gap-1.5 rounded-sm py-0.5 text-left text-text-secondary transition-colors hover:text-text-primary"
        onClick={onToggle}
      >
        <ChevronRight
          className={cn('size-3.5 shrink-0 transition-transform', !collapsed && 'rotate-90')}
          aria-hidden="true"
        />
        <span className="min-w-0 truncate">{describeSteps(message)}</span>
      </button>
      <AnimatePresence initial={false}>
        {collapsed ? null : (
          <motion.div
            key="steps"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div
              className={cn(
                'flex flex-col gap-2 border-l border-border-base pl-3',
                compact ? 'mt-1' : 'mt-1.5',
              )}
            >
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
