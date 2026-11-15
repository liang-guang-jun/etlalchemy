import { ArrowRightLeft, Link2, Pencil, Trash2 } from 'lucide-react';

import { cn } from '@/shared/lib/cn';
import { Tooltip } from '@/shared/ui';

/** Shared look of the icon-only header buttons. */
const ICON_BUTTON =
  'inline-flex size-8 items-center justify-center rounded-md text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary disabled:cursor-not-allowed disabled:text-text-disabled disabled:hover:bg-transparent';

export interface TermHeaderActionsProps {
  /** False while the term is not a draft; linking is rejected then. */
  canLink: boolean;
  onEdit: () => void;
  onMove: () => void;
  onLink: () => void;
  onDelete: () => void;
}

/**
 * Renders the icon-only action group of the term detail header.
 *
 * Each button carries a tooltip because the labels are gone, and a divider
 * separates the destructive action from the rest.
 *
 * @param props Component props.
 * @returns The header action group.
 */
export function TermHeaderActions({
  canLink,
  onEdit,
  onMove,
  onLink,
  onDelete,
}: TermHeaderActionsProps) {
  return (
    <div className="flex items-center gap-0.5">
      <Tooltip content="Edit">
        <button type="button" aria-label="Edit" className={ICON_BUTTON} onClick={onEdit}>
          <Pencil className="size-4" aria-hidden="true" />
        </button>
      </Tooltip>
      <Tooltip content="Move">
        <button type="button" aria-label="Move" className={ICON_BUTTON} onClick={onMove}>
          <ArrowRightLeft className="size-4" aria-hidden="true" />
        </button>
      </Tooltip>
      <Tooltip content="Link">
        <button
          type="button"
          aria-label="Link"
          disabled={!canLink}
          className={ICON_BUTTON}
          onClick={onLink}
        >
          <Link2 className="size-4" aria-hidden="true" />
        </button>
      </Tooltip>
      <span className="mx-1 h-4 w-px bg-border-base" aria-hidden="true" />
      <Tooltip content="Delete">
        <button
          type="button"
          aria-label="Delete"
          className={cn(ICON_BUTTON, 'hover:bg-danger/10 hover:text-danger')}
          onClick={onDelete}
        >
          <Trash2 className="size-4" aria-hidden="true" />
        </button>
      </Tooltip>
    </div>
  );
}
