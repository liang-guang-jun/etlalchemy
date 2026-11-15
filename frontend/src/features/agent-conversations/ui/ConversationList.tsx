import { useMemo, useState } from 'react';
import { MessageSquare, MoreHorizontal, Pencil, Trash2 } from 'lucide-react';

import { filterConversations, groupConversations, type AgentConversation } from '@/entities/agent';
import { cn } from '@/shared/lib/cn';
import { formatRelative } from '@/shared/lib/date';
import { ConfirmDialog, Popover, SearchInput } from '@/shared/ui';

import { useDiscardConversation } from '../api/mutation';
import { RenameConversationDialog } from './RenameConversationDialog';

export interface ConversationListProps {
  /** Conversations to render; already the whole list of the caller. */
  conversations: AgentConversation[];
  /** Conversation shown in the chat area. */
  activeConversationId: string | null;
  /** Called when the user picks a conversation. */
  onSelect: (conversationId: string) => void;
  /** Called after a conversation was discarded. */
  onDiscarded?: (conversationId: string) => void;
}

/**
 * Renders the searchable, time-grouped conversation history.
 *
 * @param props Component props.
 * @returns The list panel.
 */
export function ConversationList({
  conversations,
  activeConversationId,
  onSelect,
  onDiscarded,
}: ConversationListProps) {
  const [term, setTerm] = useState('');
  const [renaming, setRenaming] = useState<AgentConversation | null>(null);
  const [removing, setRemoving] = useState<AgentConversation | null>(null);
  const discard = useDiscardConversation();

  const groups = useMemo(
    () => groupConversations(filterConversations(conversations, term)),
    [conversations, term],
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="shrink-0 px-2 pb-2">
        <SearchInput
          value={term}
          ariaLabel="Search conversations"
          placeholder="Search conversations"
          className="w-full [&_input]:w-full"
          onChange={setTerm}
        />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-1 pb-2">
        {groups.length === 0 ? (
          <p className="px-2 py-6 text-center text-xs text-text-secondary">
            {term === '' ? 'No conversations yet.' : 'Nothing matches that search.'}
          </p>
        ) : (
          groups.map((group) => (
            <section key={group.label} className="mb-3">
              <h3 className="px-2 py-1 text-[11px] font-semibold tracking-wider text-text-disabled uppercase">
                {group.label}
              </h3>
              <ul>
                {group.items.map((conversation) => {
                  const active = conversation.conversation_id === activeConversationId;
                  return (
                    <li key={conversation.conversation_id} className="group relative">
                      <button
                        type="button"
                        aria-current={active ? 'true' : undefined}
                        onClick={() => {
                          onSelect(conversation.conversation_id);
                        }}
                        className={cn(
                          'flex w-full items-center gap-2 rounded-md py-1.5 pr-8 pl-2 text-left text-sm transition-colors',
                          active
                            ? 'bg-bg-hover font-medium text-text-primary'
                            : 'text-text-secondary hover:bg-bg-hover-subtle hover:text-text-primary',
                        )}
                      >
                        <MessageSquare
                          className="size-3.5 shrink-0 text-text-disabled"
                          aria-hidden="true"
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate">
                            {conversation.title === '' ? 'New conversation' : conversation.title}
                          </span>
                          <span className="block truncate text-[11px] text-text-disabled">
                            {formatRelative(conversation.last_activity_at)}
                          </span>
                        </span>
                      </button>
                      <span className="absolute top-1.5 right-1 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
                        <Popover
                          label="Conversation actions"
                          align="end"
                          panelClassName="w-40"
                          triggerClassName="size-6 text-text-secondary hover:bg-bg-surface"
                          trigger={<MoreHorizontal className="size-4" aria-hidden="true" />}
                        >
                          {(close) => (
                            <div className="flex flex-col">
                              <button
                                type="button"
                                className="flex items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm hover:bg-bg-hover"
                                onClick={() => {
                                  close();
                                  setRenaming(conversation);
                                }}
                              >
                                <Pencil className="size-3.5" aria-hidden="true" />
                                Rename
                              </button>
                              <button
                                type="button"
                                className="flex items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm text-danger hover:bg-danger/10"
                                onClick={() => {
                                  close();
                                  setRemoving(conversation);
                                }}
                              >
                                <Trash2 className="size-3.5" aria-hidden="true" />
                                Delete
                              </button>
                            </div>
                          )}
                        </Popover>
                      </span>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))
        )}
      </div>

      <RenameConversationDialog
        conversation={renaming}
        onClose={() => {
          setRenaming(null);
        }}
      />

      <ConfirmDialog
        open={removing !== null}
        title="Delete conversation"
        description="The conversation and its messages are removed from your history."
        confirmLabel="Delete"
        danger
        loading={discard.isPending}
        onCancel={() => {
          setRemoving(null);
        }}
        onConfirm={() => {
          if (removing === null) {
            return;
          }
          const conversationId = removing.conversation_id;
          discard.mutate(conversationId, {
            onSuccess: () => {
              onDiscarded?.(conversationId);
              setRemoving(null);
            },
          });
        }}
      />
    </div>
  );
}
