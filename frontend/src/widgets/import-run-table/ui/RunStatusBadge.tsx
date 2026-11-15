import { motion } from 'motion/react';

import type { BadgeTone } from '@/shared/ui';
import { Badge } from '@/shared/ui';

/** Badge tint per run status. */
const STATUS_TONES: Record<string, BadgeTone> = {
  pending: 'warning',
  succeeded: 'success',
  failed: 'danger',
  abandoned: 'neutral',
};

export interface RunStatusBadgeProps {
  status: string;
}

/**
 * Renders the status of an import run and bounces when it changes.
 *
 * The status element is keyed by the status itself, so React remounts it on a
 * change and the spring animation plays exactly once per transition.
 *
 * @param props Component props.
 * @returns The status badge.
 */
export function RunStatusBadge({ status }: RunStatusBadgeProps) {
  return (
    <span className="inline-flex flex-col gap-1">
      <motion.span
        key={status}
        initial={{ scale: 0.8, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: 'spring', stiffness: 480, damping: 18 }}
        className="inline-flex"
      >
        <Badge tone={STATUS_TONES[status] ?? 'neutral'}>{status}</Badge>
      </motion.span>
      {status === 'pending' ? (
        <motion.span
          className="block h-0.5 w-14 overflow-hidden rounded-full bg-warning/25"
          aria-hidden="true"
        >
          <motion.span
            className="block h-full w-1/2 rounded-full bg-warning"
            animate={{ x: ['-100%', '200%'] }}
            transition={{ duration: 1.2, repeat: Infinity, ease: 'easeInOut' }}
          />
        </motion.span>
      ) : null}
    </span>
  );
}
