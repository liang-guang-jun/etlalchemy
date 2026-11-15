import { useEffect, useState } from 'react';
import { Check } from 'lucide-react';

import type { AgentConversation } from '@/entities/agent';
import { Button, Dialog, Input } from '@/shared/ui';

import { useRenameConversation } from '../api/mutation';

export interface RenameConversationDialogProps {
  /** Conversation to rename, or `null` while the dialog is closed. */
  conversation: AgentConversation | null;
  /** Closes the dialog. */
  onClose: () => void;
}

/**
 * Renders the rename dialog shared by the history list and the chat header.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function RenameConversationDialog({ conversation, onClose }: RenameConversationDialogProps) {
  const [title, setTitle] = useState(conversation?.title ?? '');
  const rename = useRenameConversation();

  useEffect(() => {
    setTitle(conversation?.title ?? '');
  }, [conversation]);

  return (
    <Dialog
      open={conversation !== null}
      title="Rename conversation"
      size="sm"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            icon={<Check className="size-4" />}
            loading={rename.isPending}
            disabled={title.trim() === ''}
            onClick={() => {
              if (conversation === null) {
                return;
              }
              rename.mutate({ conversation, title }, { onSuccess: onClose });
            }}
          >
            Save
          </Button>
        </>
      }
    >
      <Input
        aria-label="Conversation title"
        value={title}
        autoFocus
        onChange={(event) => {
          setTitle(event.target.value);
        }}
      />
    </Dialog>
  );
}
