import { motion } from 'motion/react';
import { useId } from 'react';

import { cn } from '@/shared/lib/cn';

import { ENTITY_DETAIL_LEVELS, type EntityDetailLevel } from '../model/detail-level';

export interface DetailLevelSwitchProps {
  value: EntityDetailLevel;
  onChange: (value: EntityDetailLevel) => void;
}

/**
 * Renders the segmented control that decides how much of an entity card is
 * shown: the table only, the columns used by relationships, or every column.
 *
 * @param props Component props.
 * @returns The switch element.
 */
export function DetailLevelSwitch({ value, onChange }: DetailLevelSwitchProps) {
  const indicatorId = useId();

  return (
    <div
      role="radiogroup"
      aria-label="Entity details"
      className="flex shrink-0 items-center gap-0.5 rounded-md border border-border-base bg-bg-canvas p-0.5"
    >
      {ENTITY_DETAIL_LEVELS.map((level) => {
        const selected = level.value === value;
        return (
          <button
            key={level.value}
            type="button"
            role="radio"
            aria-checked={selected}
            title={level.hint}
            onClick={() => {
              onChange(level.value);
            }}
            className={cn(
              'relative flex h-6 items-center rounded-sm px-2.5 text-xs transition-colors',
              selected
                ? 'font-medium text-text-primary'
                : 'text-text-secondary hover:text-text-primary',
            )}
          >
            {selected ? (
              <motion.span
                layoutId={`detail-level-${indicatorId}`}
                aria-hidden="true"
                className="absolute inset-0 rounded-sm bg-bg-surface shadow-sm"
                transition={{ type: 'spring', stiffness: 420, damping: 34 }}
              />
            ) : null}
            <span className="relative">{level.label}</span>
          </button>
        );
      })}
    </div>
  );
}
