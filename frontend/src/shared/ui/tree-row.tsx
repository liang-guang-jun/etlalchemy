import { AnimatePresence, motion } from 'motion/react';
import { ChevronRight, MoreHorizontal, Plus } from 'lucide-react';
import type { HTMLAttributes, ReactNode } from 'react';
import { Link } from 'react-router';

import { cn } from '@/shared/lib/cn';
import { highlightMatches } from '@/shared/lib/highlight-text';
import { DropdownMenu, type DropdownMenuItem } from './dropdown-menu';

export interface TreeRowProps {
  /** Nesting level; the first level is `0`. */
  depth: number;
  label: string;
  icon: ReactNode;
  to: string;
  active: boolean;
  /** Whether the node has children to disclose; omit for leaves. */
  expanded?: boolean;
  onToggle?: () => void;
  /** Hover action that creates a child node. */
  onCreate?: () => void;
  createLabel?: string;
  menuItems?: DropdownMenuItem[];
  /** Replaces the built-in menu button, for stateful action menus. */
  actions?: ReactNode;
  /** Small marker rendered between the label and the hover actions. */
  trailing?: ReactNode;
  /** Search term whose occurrences are marked inside the label. */
  highlight?: string;
  /** Extra attributes of the row element, e.g. HTML5 drag and drop handlers. */
  rowProps?: HTMLAttributes<HTMLDivElement>;
  children?: ReactNode;
}

/** Horizontal offset of one nesting level, in pixels. */
const INDENT = 12;

/**
 * Renders one row of the resource tree with its disclosure arrow, type icon,
 * link and hover actions.
 *
 * @param props Component props.
 * @returns The tree row, plus its children while expanded.
 */
export function TreeRow({
  depth,
  label,
  icon,
  to,
  active,
  expanded = false,
  onToggle,
  onCreate,
  createLabel,
  menuItems,
  actions,
  trailing,
  highlight = '',
  rowProps,
  children,
}: TreeRowProps) {
  const expandable = onToggle !== undefined;
  const hasActions = onCreate !== undefined || menuItems !== undefined || actions !== undefined;

  return (
    <div>
      <div
        {...rowProps}
        className={cn(
          'group/row flex h-8 items-center gap-1 rounded-sm border-l-2 pr-1 transition-colors',
          active
            ? 'border-brand bg-border-base font-medium text-text-primary'
            : 'border-transparent text-text-secondary hover:bg-bg-hover-subtle hover:text-text-primary',
        )}
        style={{ paddingLeft: 2 + depth * INDENT }}
      >
        {expandable ? (
          <button
            type="button"
            aria-label={`${expanded ? 'Collapse' : 'Expand'} ${label}`}
            aria-expanded={expanded}
            onClick={onToggle}
            className="flex size-5 shrink-0 items-center justify-center rounded-sm text-text-secondary transition-colors hover:text-text-primary"
          >
            <motion.span
              animate={{ rotate: expanded ? 90 : 0 }}
              transition={{ duration: 0.15, ease: 'easeOut' }}
              className="flex"
            >
              <ChevronRight className="size-3.5" aria-hidden="true" />
            </motion.span>
          </button>
        ) : (
          <span className="size-5 shrink-0" aria-hidden="true" />
        )}

        <Link
          to={to}
          className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden py-1 text-sm"
        >
          <span className="flex shrink-0 items-center">{icon}</span>
          <span className="min-w-0 truncate">{highlightMatches(label, highlight)}</span>
        </Link>

        {trailing === undefined ? null : (
          <span className="flex shrink-0 items-center">{trailing}</span>
        )}

        {hasActions ? (
          <span className="flex shrink-0 translate-x-1 items-center gap-1 opacity-0 transition-all duration-200 group-hover/row:translate-x-0 group-hover/row:opacity-100 group-focus-within/row:translate-x-0 group-focus-within/row:opacity-100">
            {onCreate === undefined ? null : (
              <button
                type="button"
                aria-label={createLabel ?? `New child of ${label}`}
                title={createLabel ?? 'New child'}
                onClick={(event) => {
                  event.stopPropagation();
                  onCreate();
                }}
                className="flex size-5 items-center justify-center text-text-disabled transition-colors hover:text-text-primary"
              >
                <Plus className="size-3.5" aria-hidden="true" />
              </button>
            )}
            {menuItems === undefined ? null : (
              <DropdownMenu
                iconOnly
                label={`Actions for ${label}`}
                icon={<MoreHorizontal className="size-3.5" aria-hidden="true" />}
                items={menuItems}
                triggerClassName="size-5 text-text-disabled hover:bg-transparent hover:text-text-primary"
              />
            )}
            {actions}
          </span>
        ) : null}
      </div>

      <AnimatePresence initial={false}>
        {expanded && children !== undefined ? (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className="overflow-hidden"
          >
            {children}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

export interface TreeMessageProps {
  depth: number;
  text: string;
}

/**
 * Renders a muted placeholder inside the tree, aligned with the rows of its
 * nesting level.
 *
 * @param props Component props.
 * @returns The placeholder line.
 */
export function TreeMessage({ depth, text }: TreeMessageProps) {
  return (
    <p
      className="truncate py-1 text-xs text-text-disabled"
      style={{ paddingLeft: 2 + depth * INDENT + 24 }}
    >
      {text}
    </p>
  );
}
