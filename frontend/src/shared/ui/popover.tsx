import { useEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

import { cn } from '@/shared/lib/cn';

export interface PopoverProps {
  /** Accessible name of the trigger. */
  label: string;
  /** Trigger content, usually an icon or a dot. */
  trigger: ReactNode;
  /** Extra classes of the trigger button. */
  triggerClassName?: string;
  /** Panel content; the render prop receives a `close` callback. */
  children: ReactNode | ((close: () => void) => ReactNode);
  /** Horizontal alignment of the panel relative to the trigger. */
  align?: 'start' | 'end';
  /** Extra classes of the panel, typically its width. */
  panelClassName?: string;
}

interface Placement {
  top: number;
  left?: number;
  right?: number;
}

/**
 * Renders a trigger that opens a floating panel in a portal.
 *
 * The panel escapes scrolling containers, closes on an outside click, Escape,
 * resize or scroll, and flips above the trigger when there is no room below.
 *
 * @param props Component props.
 * @returns The trigger and its panel.
 */
export function Popover({
  label,
  trigger,
  triggerClassName,
  children,
  align = 'start',
  panelClassName,
}: PopoverProps) {
  const [open, setOpen] = useState(false);
  const [placement, setPlacement] = useState<Placement | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) {
      return undefined;
    }
    const close = () => {
      setOpen(false);
    };
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (
        triggerRef.current?.contains(target) === true ||
        panelRef.current?.contains(target) === true
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
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    window.addEventListener('resize', close);
    window.addEventListener('scroll', close, true);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
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
    // The panel is short (a swatch grid); 220px keeps it above the fold.
    const height = 220;
    const fitsBelow = rect.bottom + height + 8 <= window.innerHeight;
    setPlacement({
      top: fitsBelow ? rect.bottom + 6 : Math.max(8, rect.top - height - 6),
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
        aria-label={label}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={label}
        onClick={toggle}
        className={cn(
          'inline-flex cursor-pointer items-center justify-center rounded-md transition-colors',
          triggerClassName,
        )}
      >
        {trigger}
      </button>
      {open && placement !== null
        ? createPortal(
            <div
              ref={panelRef}
              role="dialog"
              aria-label={label}
              style={{ top: placement.top, left: placement.left, right: placement.right }}
              className={cn(
                'fixed z-50 rounded-lg border border-border-base bg-bg-surface p-3 shadow-md',
                panelClassName,
              )}
            >
              {typeof children === 'function'
                ? children(() => {
                    setOpen(false);
                  })
                : children}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
