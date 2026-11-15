import { useState } from 'react';
import { MoreHorizontal } from 'lucide-react';

import { useTerm } from '@/entities/term';
import { DropdownMenu } from '@/shared/ui';

import { DiscardTermConfirm, EditTermDialog, LinkTermDialog, MoveTermDialog } from './TermDialogs';

type TermAction = 'edit' | 'move' | 'link' | 'delete';

export interface TermActionsMenuProps {
  domainId: string;
  termId: string;
  name: string;
  /** Lifecycle status of the term; only drafts may be linked. */
  status: string;
}

interface TermActionDialogsProps {
  domainId: string;
  termId: string;
  action: TermAction;
  onClose: () => void;
}

/**
 * Loads one term and renders the dialog requested from the menu.
 *
 * @param props Component props.
 * @returns The dialog, or `null` while the term is loading.
 */
function TermActionDialogs({ domainId, termId, action, onClose }: TermActionDialogsProps) {
  const term = useTerm(domainId, termId);
  if (term.data === undefined) {
    return null;
  }
  if (action === 'edit') {
    return (
      <EditTermDialog
        open
        domainId={domainId}
        term={term.data}
        editable={term.data.status === 'draft'}
        onClose={onClose}
      />
    );
  }
  if (action === 'move') {
    return <MoveTermDialog open domainId={domainId} term={term.data} onClose={onClose} />;
  }
  if (action === 'link') {
    return <LinkTermDialog open domainId={domainId} term={term.data} onClose={onClose} />;
  }
  return (
    <DiscardTermConfirm
      open
      domainId={domainId}
      term={term.data}
      onClose={onClose}
      onDiscarded={onClose}
    />
  );
}

/**
 * Renders the compact term action menu used by the tree and the term table.
 *
 * Edit, move, link and delete need the full term, so it is fetched only after
 * an action is picked.
 *
 * @param props Component props.
 * @returns The icon menu with its dialogs.
 */
export function TermActionsMenu({ domainId, termId, name, status }: TermActionsMenuProps) {
  const [action, setAction] = useState<TermAction | null>(null);

  return (
    <>
      <DropdownMenu
        iconOnly
        label={`Actions for ${name}`}
        icon={<MoreHorizontal className="size-3.5" aria-hidden="true" />}
        triggerClassName="size-5 text-text-disabled hover:bg-transparent hover:text-text-primary"
        items={[
          { label: 'Rename / edit', onSelect: () => setAction('edit') },
          { label: 'Move under another term', onSelect: () => setAction('move') },
          {
            label: 'Link to catalog object',
            disabled: status !== 'draft',
            onSelect: () => setAction('link'),
          },
          { label: 'Delete term', danger: true, onSelect: () => setAction('delete') },
        ]}
      />
      {action === null ? null : (
        <TermActionDialogs
          domainId={domainId}
          termId={termId}
          action={action}
          onClose={() => setAction(null)}
        />
      )}
    </>
  );
}
