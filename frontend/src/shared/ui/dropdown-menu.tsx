import { useEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { ChevronDown } from 'lucide-react';

import { cn } from '@/shared/lib/cn';

export interface DropdownMenuItem {
  label: string;
  onSelect: () => void;
  danger?: boolean;
  disabled?: boolean;
}

export interface DropdownMenuProps {
  label: string;
  items: DropdownMenuItem[];
  align?: 'start' | 'end';
  icon?: ReactNode;
  /** Renders only the icon in a square trigger; `label` becomes the accessible name. */
  iconOnly?: boolean;
  /** Extra classes for the trigger button. */
  triggerClassName?: string;
}

interface MenuPlacement {
  top: number;
  left?: number;
  right?: number;
}

/** Approximate height of one menu row, used to flip the menu above the trigger. */
const ITEM_HEIGHT = 36;

/**
 * Renders a button that opens a menu of actions.
 *
 * The menu lives in a portal so it is never clipped by a scrolling panel or a
 * table container.
 *
 * @param props Component props.
 * @returns The dropdown element.
 */
export function DropdownMenu({
  label,
  items,
  align = 'end',
  icon,
  iconOnly = false,
  triggerClassName,
}: DropdownMenuProps) {
  const [open, setOpen] = useState(false);
  const [placement, setPlacement] = useState<MenuPlacement | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLMenuElement>(null);

  useEffect(() => {
    if (!open) {
      return undefined;
    }
    const close = () => {
      setOpen(false);
    };
    const onDocumentClick = (event: MouseEvent) => {
      const target = event.target as Node;
      if (
        triggerRef.current?.contains(target) === true ||
        menuRef.current?.contains(target) === true
      ) {
        return;
      }
      close();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        close();
      }
    };
    document.addEventListener('mousedown', onDocumentClick);
    document.addEventListener('keydown', onKeyDown);
    window.addEventListener('resize', close);
    window.addEventListener('scroll', close, true);
    return () => {
      document.removeEventListener('mousedown', onDocumentClick);
      document.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('resize', close);
      window.removeEventListener('scroll', close, true);
    };
  }, [open]);

  const toggle = () => {
    if (open) {
      setOpen(false);
      return;
    }
    const rect = triggerRef.current?.getBoundingClientRect();
    if (rect === undefined) {
      return;
    }
    const height = items.length * ITEM_HEIGHT + 8;
    const fitsBelow = rect.bottom + height + 8 <= window.innerHeight;
    setPlacement({
      top: fitsBelow ? rect.bottom + 4 : Math.max(8, rect.top - height - 4),
      ...(align === 'end'
        ? { right: Math.max(8, window.innerWidth - rect.right) }
        : { left: Math.max(8, rect.left) }),
    });
    setOpen(true);
  };

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={iconOnly ? label : undefined}
        title={iconOnly ? label : undefined}
        onClick={toggle}
        className={cn(
          iconOnly
            ? 'inline-flex size-6 items-center justify-center rounded-sm text-text-secondary transition-colors hover:bg-bg-surface hover:text-text-primary'
            : 'inline-flex h-8 items-center gap-1 rounded-sm border border-border-base bg-bg-surface px-2 text-xs text-text-secondary hover:bg-bg-hover hover:text-text-primary',
          triggerClassName,
        )}
      >
        {icon}
        {iconOnly ? null : label}
        {iconOnly ? null : <ChevronDown className="size-3" aria-hidden="true" />}
      </button>
      {open && placement !== null
        ? createPortal(
            <menu
              ref={menuRef}
              role="menu"
              aria-label={label}
              style={{ top: placement.top, left: placement.left, right: placement.right }}
              className="fixed z-50 min-w-40 rounded-md border border-border-base bg-bg-surface py-1 shadow-md"
            >
              {items.map((item) => (
                <li key={item.label}>
                  <button
                    type="button"
                    role="menuitem"
                    disabled={item.disabled === true}
                    onClick={() => {
                      setOpen(false);
                      item.onSelect();
                    }}
                    className={cn(
                      'w-full px-3 py-2 text-left text-sm whitespace-nowrap hover:bg-bg-hover disabled:cursor-not-allowed disabled:text-text-disabled',
                      item.danger === true ? 'text-danger' : 'text-text-primary',
                    )}
                  >
                    {item.label}
                  </button>
                </li>
              ))}
            </menu>,
            document.body,
          )
        : null}
    </>
  );
}
