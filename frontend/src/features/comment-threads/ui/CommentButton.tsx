import { MessagesSquare } from 'lucide-react';

import { TARGET_NOUNS, useOpenThreadCount, type CommentTarget } from '@/entities/comment';
import { ActionIconButton, Button } from '@/shared/ui';

import { openComments } from '../model/store';

export interface CommentButtonProps {
  /** Object the discussion hangs off. */
  target: CommentTarget;
  /** `icon` for a header action bar, `button` for an inline label. */
  variant?: 'icon' | 'button';
}

/**
 * Renders the entry point of the discussion of one object.
 *
 * The open-thread count doubles as the unread hint the PRD asks for: it is 0
 * for a quiet object, so the badge only shows up once someone is talking.
 *
 * @param props Component props.
 * @returns The discussion button.
 */
export function CommentButton({ target, variant = 'icon' }: CommentButtonProps) {
  const count = useOpenThreadCount(target.type, target.id);
  const label = `Discuss this ${TARGET_NOUNS[target.type].toLowerCase()}`;
  const title = count === 0 ? label : `${label} (${count} open)`;

  if (variant === 'button') {
    return (
      <Button
        size="sm"
        variant="secondary"
        aria-label={title}
        title={title}
        onClick={() => {
          openComments(target);
        }}
      >
        <MessagesSquare className="size-3.5" aria-hidden="true" />
        Discuss
        {count === 0 ? null : (
          <span className="ml-1 rounded-sm bg-brand px-1 text-[10px] font-semibold text-brand-text">
            {count}
          </span>
        )}
      </Button>
    );
  }

  return (
    <ActionIconButton
      label={title}
      onClick={() => {
        openComments(target);
      }}
      icon={
        <span className="relative flex">
          <MessagesSquare className="size-4" aria-hidden="true" />
          {count === 0 ? null : (
            <span className="absolute -top-1.5 -right-2 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-brand px-1 text-[9px] font-semibold text-brand-text">
              {count > 9 ? '9+' : count}
            </span>
          )}
        </span>
      }
    />
  );
}
