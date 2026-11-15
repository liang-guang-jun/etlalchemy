import { useEffect, useRef, useState } from 'react';
import { PanelLeftClose, PanelLeftOpen, Pencil, Plus } from 'lucide-react';
import { useNavigate, useLocation, useParams } from 'react-router';

import {
  useActiveConversation,
  useAgentStore,
  useConversationFeed,
  useConversationHydration,
  useTranscript,
} from '@/entities/agent';
import { Composer, useAgentChat } from '@/features/agent-chat';
import { ConversationList, RenameConversationDialog } from '@/features/agent-conversations';
import { ProviderSwitcher } from '@/features/agent-providers';
import { MessageList } from '@/widgets/agent-chat';
import { isApiError } from '@/shared/api/error';
import { describeLocation } from '@/shared/config/navigation';
import { Badge, Button, Skeleton, Switch, toast } from '@/shared/ui';

/** Prompts offered before the first message of a new conversation. */
const SUGGESTIONS = [
  'Which tables have no description yet?',
  'Show the entities and relationships of every semantic model',
  'List the business terms that are still drafts',
];

/** Local key of the sidebar width preference. */
const SIDEBAR_STORAGE_KEY = 'etlalchemy.agent.sidebar-collapsed';

/**
 * Renders the full-page agent workspace.
 *
 * The left panel is the conversation history, the right panel is the chat. The
 * conversation comes from the URL (`/agent/:conversationId`) or from the shared
 * store, so collapsing the floating widget lands on the same conversation.
 *
 * @returns The agent page.
 */
export default function AgentPage() {
  const params = useParams<{ conversationId?: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const feed = useConversationFeed();
  const activeConversationId = useAgentStore((state) => state.activeConversationId);
  const setActiveConversation = useAgentStore((state) => state.setActiveConversation);
  const removeConversation = useAgentStore((state) => state.removeConversation);
  const autoApprove = useAgentStore((state) => state.autoApprove);
  const setAutoApprove = useAgentStore((state) => state.setAutoApprove);
  const conversations = useAgentStore((state) => state.conversations);
  const active = useActiveConversation();
  const conversationId = params.conversationId ?? activeConversationId;
  const messages = useConversationHydration(conversationId);
  const transcript = useTranscript(conversationId);
  const chat = useAgentChat(conversationId, {
    onConversationCreated: (created) => {
      navigate(`/agent/${created}`, { replace: true });
    },
  });
  const [collapsed, setCollapsed] = useState(
    () => window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === '1',
  );
  const [renaming, setRenaming] = useState(false);
  const scrollerRef = useRef<HTMLDivElement>(null);
  // Inside the workspace there is no "current section" to hand to the agent.
  const section = describeLocation(location.pathname);
  const contextLabels = section === null || location.pathname.startsWith('/agent') ? [] : [section];

  // The URL is the source of truth when it names a conversation, but only a URL
  // that *changed* may select one: deleting the open conversation resets the store
  // while the address bar still carries its id for one render, and re-applying
  // that id would resurrect a conversation that no longer exists.
  const urlConversationId = params.conversationId ?? null;
  const appliedUrl = useRef<string | null>(null);
  useEffect(() => {
    if (urlConversationId === null || appliedUrl.current === urlConversationId) {
      return;
    }
    appliedUrl.current = urlConversationId;
    setActiveConversation(urlConversationId);
  }, [urlConversationId, setActiveConversation]);

  // A stale deep link (deleted conversation) falls back to a fresh chat and drops
  // whatever the store still holds for it.
  useEffect(() => {
    if (conversationId === null || messages.error === null) {
      return;
    }
    if (!isApiError(messages.error) || messages.error.status !== 404) {
      return;
    }
    removeConversation(conversationId);
    navigate('/agent', { replace: true });
    toast.info('That conversation no longer exists.');
  }, [conversationId, messages.error, navigate, removeConversation]);

  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, collapsed ? '1' : '0');
  }, [collapsed]);

  // Following the stream belongs to `MessageList`: it renders in this scroller and
  // in the floating widget, so one implementation covers both surfaces.
  const openConversation = (id: string) => {
    setActiveConversation(id);
    navigate(`/agent/${id}`);
  };

  const startNew = () => {
    setActiveConversation(null);
    navigate('/agent');
  };

  return (
    <div className="flex h-full min-h-0 bg-agent-canvas text-text-primary">
      {collapsed ? null : (
        <aside className="flex w-[260px] min-w-[260px] flex-col border-r border-border-base bg-agent-panel">
          <div className="p-2">
            <Button
              className="w-full justify-start"
              icon={<Plus className="size-4" />}
              onClick={startNew}
            >
              New chat
            </Button>
          </div>
          {feed.isPending && conversations.length === 0 ? (
            <div className="p-2">
              <Skeleton lines={8} />
            </div>
          ) : (
            <ConversationList
              conversations={conversations}
              activeConversationId={conversationId}
              onSelect={openConversation}
              onDiscarded={(discarded) => {
                if (discarded !== conversationId) {
                  return;
                }
                // The mutation already dropped the transcript and the list entry;
                // the URL has to follow, and it replaces the dead link in history.
                setActiveConversation(null);
                navigate('/agent', { replace: true });
              }}
            />
          )}
        </aside>
      )}

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border-base px-3">
          <button
            type="button"
            aria-label={
              collapsed ? 'Expand the conversation panel' : 'Collapse the conversation panel'
            }
            title={collapsed ? 'Expand' : 'Collapse'}
            onClick={() => {
              setCollapsed(!collapsed);
            }}
            className="flex size-8 items-center justify-center rounded-md text-text-secondary hover:bg-bg-hover hover:text-text-primary"
          >
            {collapsed ? (
              <PanelLeftOpen className="size-4" aria-hidden="true" />
            ) : (
              <PanelLeftClose className="size-4" aria-hidden="true" />
            )}
          </button>

          <div className="min-w-0 flex-1">
            {active === null ? (
              <span className="truncate text-sm font-medium text-text-primary">
                New conversation
              </span>
            ) : (
              // Double-click renames, matching the conversation list menu.
              <button
                type="button"
                aria-label="Rename conversation"
                title="Double-click to rename"
                onDoubleClick={() => {
                  setRenaming(true);
                }}
                className="flex max-w-full min-w-0 items-center gap-2 rounded-sm px-1 text-left"
              >
                <span className="truncate text-sm font-medium">
                  {active.title === '' ? 'New conversation' : active.title}
                </span>
                <Pencil className="size-3 shrink-0 text-text-disabled" aria-hidden="true" />
              </button>
            )}
          </div>

          {transcript.run.status === 'awaiting_approval' ? (
            <Badge tone="warning">awaiting approval</Badge>
          ) : null}
          <label className="flex shrink-0 items-center gap-1.5 text-[11px] text-text-secondary">
            <Switch
              checked={autoApprove}
              onCheckedChange={setAutoApprove}
              label="Auto-approve destructive tools"
            />
            <span aria-hidden="true">auto-approve</span>
          </label>
          <ProviderSwitcher conversation={active} />
          <button
            type="button"
            aria-label="New conversation"
            title="New conversation"
            onClick={startNew}
            className="flex size-8 items-center justify-center rounded-md text-text-secondary hover:bg-bg-hover hover:text-text-primary"
          >
            <Plus className="size-4" aria-hidden="true" />
          </button>
        </header>

        <div ref={scrollerRef} className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto">
          {conversationId !== null && messages.isPending && transcript.messages.length === 0 ? (
            <div className="p-6">
              <Skeleton lines={6} />
            </div>
          ) : (
            <MessageList
              conversationId={conversationId}
              transcript={transcript}
              suggestions={SUGGESTIONS}
              onSuggestion={(prompt) => {
                void chat.send(prompt);
              }}
              onEditMessage={(messageId, content) => {
                void chat.edit(messageId, content);
              }}
            />
          )}
        </div>

        <Composer
          conversationId={conversationId}
          onConversationCreated={(created) => {
            navigate(`/agent/${created}`, { replace: true });
          }}
          contextLabels={contextLabels}
        />
      </section>

      <RenameConversationDialog
        conversation={renaming ? active : null}
        onClose={() => {
          setRenaming(false);
        }}
      />
    </div>
  );
}
