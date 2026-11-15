import type { Term, TermTransition } from '@/entities/term';
import { cn } from '@/shared/lib/cn';
import { DropdownMenu, type DropdownMenuItem } from '@/shared/ui';

import { useTransitionTerm } from '../api/mutation';

/** Status colours of the badge-like trigger: draft grey, approved green, deprecated red. */
const STATUS_TRIGGER: Record<string, string> = {
  draft: 'border-border-base bg-bg-hover-subtle text-text-secondary',
  approved: 'border-success/30 bg-success/10 text-success',
  deprecated: 'border-danger/30 bg-danger/10 text-danger',
};

interface Transition {
  transition: TermTransition;
  label: string;
  danger?: boolean;
}

const TRANSITIONS: Record<string, Transition[]> = {
  draft: [{ transition: 'approve', label: 'Approve' }],
  approved: [
    { transition: 'reopen', label: 'Reopen' },
    { transition: 'deprecate', label: 'Deprecate', danger: true },
  ],
  deprecated: [{ transition: 'reactivate', label: 'Reactivate' }],
};

export interface TermStatusMenuProps {
  domainId: string;
  term: Term;
}

/**
 * Renders the term status as a badge that opens the allowed lifecycle commands.
 *
 * @param props Component props.
 * @returns The status dropdown.
 */
export function TermStatusMenu({ domainId, term }: TermStatusMenuProps) {
  const mutation = useTransitionTerm(domainId);
  const transitions = TRANSITIONS[term.status] ?? [];

  const items: DropdownMenuItem[] = transitions.map((entry) => ({
    label: entry.label,
    danger: entry.danger,
    onSelect: () => {
      mutation.mutate({ termId: term.term_id, transition: entry.transition, argument: '' });
    },
  }));

  return (
    <DropdownMenu
      label={term.status}
      align="start"
      items={items}
      icon={
        <span
          aria-hidden="true"
          className={cn(
            'size-1.5 rounded-full',
            term.status === 'approved'
              ? 'bg-success'
              : term.status === 'deprecated'
                ? 'bg-danger'
                : 'bg-text-disabled',
          )}
        />
      }
      triggerClassName={cn(
        'h-6 rounded-full border px-2 py-0.5 text-[11px] font-semibold tracking-wide uppercase',
        STATUS_TRIGGER[term.status] ?? STATUS_TRIGGER.draft,
        mutation.isPending && 'opacity-60',
      )}
    />
  );
}
