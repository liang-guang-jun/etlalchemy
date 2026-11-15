import { useEffect, useRef, useState } from 'react';

import type { Term } from '@/entities/term';
import { ColorDot, ColorPicker, Popover } from '@/shared/ui';

import { useChangeTerm } from '../api/mutation';

/** Delay that batches the continuous events of the native colour dialog. */
const COMMIT_DELAY = 350;

export interface TermColorPickerProps {
  domainId: string;
  term: Term;
}

/**
 * Renders the term colour dot as a button that opens the colour picker.
 *
 * Picking a colour patches the term; the request is debounced so dragging the
 * native picker does not fire one command per frame.
 *
 * @param props Component props.
 * @returns The colour dot with its popover.
 */
export function TermColorPicker({ domainId, term }: TermColorPickerProps) {
  const mutation = useChangeTerm(domainId, term.term_id);
  const [value, setValue] = useState(term.color);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setValue(term.color);
  }, [term.color]);

  useEffect(
    () => () => {
      if (timer.current !== null) {
        clearTimeout(timer.current);
      }
    },
    [],
  );

  const commit = (next: string) => {
    setValue(next);
    if (timer.current !== null) {
      clearTimeout(timer.current);
    }
    timer.current = setTimeout(() => {
      timer.current = null;
      if (next !== term.color) {
        mutation.mutate({ color: next });
      }
    }, COMMIT_DELAY);
  };

  return (
    <Popover
      label="Change colour"
      align="start"
      panelClassName="w-64"
      triggerClassName="-ml-2 size-6 rounded-full hover:bg-bg-hover"
      trigger={
        <ColorDot color={term.color} className="size-3.5" title={term.color || 'No colour'} />
      }
    >
      {() => (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold tracking-wider text-text-secondary uppercase">
              Term colour
            </span>
            <span className="font-mono text-[11px] text-text-disabled">{value || 'none'}</span>
          </div>
          <ColorPicker
            value={value}
            disabled={mutation.isPending}
            onChange={commit}
            label="Term colour"
          />
        </div>
      )}
    </Popover>
  );
}
