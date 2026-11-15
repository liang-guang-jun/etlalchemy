import { create } from 'zustand';

import type { AgentApprovalRow, AgentConversation } from '../api/schema';
import type { AgentEvent } from './events';
import {
  appendUserMessage,
  applyAgentEvent,
  cloneTranscript,
  emptyTranscript,
  EMPTY_TRANSCRIPT,
  markInterrupted,
  messageFromRow,
  unfoldSteps,
  type AgentApproval,
  type AgentMessage,
  type AgentRunStatus,
  type AgentTranscript,
} from './transcript';
/** Input of {@link AgentState.beginRun}. */
export interface BeginRunInput {
  /** Run reported by the provider, when it is already known. */
  runId?: string | null;
}

/** Key the auto-approve switch is persisted under. */
const AUTO_APPROVE_KEY = 'etlalchemy.agent.auto-approve';

/** Key the provider of the next new conversation is persisted under. */
const PENDING_PROVIDER_KEY = 'etlalchemy.agent.provider';

/**
 * Reads the stored switch, which defaults to on.
 *
 * @returns `true` unless the reader turned it off.
 */
function readAutoApprove(): boolean {
  try {
    return globalThis.localStorage.getItem(AUTO_APPROVE_KEY) !== '0';
  } catch {
    return true;
  }
}

/**
 * Reads the provider chosen for the next new conversation.
 *
 * @returns The provider id, or `null` for the server default.
 */
function readPendingProvider(): string | null {
  try {
    return globalThis.localStorage.getItem(PENDING_PROVIDER_KEY);
  } catch {
    return null;
  }
}

interface AgentState {
  /** Conversations of the caller, as last read from the server. */
  conversations: AgentConversation[];
  /** Conversation both surfaces show, or `null` for a fresh chat. */
  activeConversationId: string | null;
  /** Transcripts keyed by conversation id; filled lazily. */
  transcripts: Record<string, AgentTranscript>;
  /**
   * Fold choice the user made per message id.
   *
   * It lives outside the transcript so a streamed update of the message never
   * throws the choice away, and `null` means "follow the transcript".
   */
  collapsedOverrides: Record<string, boolean>;
  /** Whether the floating widget shows its popover. */
  widgetOpen: boolean;
  /**
   * Whether destructive tools run without asking for a decision.
   *
   * A reader preference, shared by both chat surfaces and applied per request:
   * the run simply never pauses for an approval.
   */
  autoApprove: boolean;
  /**
   * Provider the next new conversation starts with, or `null` for the server
   * default. A conversation that already exists keeps its own provider.
   */
  pendingProviderId: string | null;
  /** Toggles {@link autoApprove} and remembers the choice. */
  setAutoApprove: (enabled: boolean) => void;
  /** Selects the provider of the next new conversation and remembers it. */
  setPendingProvider: (providerId: string | null) => void;
  /** Replaces the conversation list. */
  setConversations: (conversations: AgentConversation[]) => void;
  /** Inserts or updates one conversation. */
  upsertConversation: (conversation: AgentConversation) => void;
  /** Drops one conversation and its transcript. */
  removeConversation: (conversationId: string) => void;
  /** Selects the conversation both surfaces show. */
  setActiveConversation: (conversationId: string | null) => void;
  /** Replaces the messages of a conversation with the persisted ones. */
  hydrateMessages: (
    conversationId: string,
    rows: readonly Parameters<typeof messageFromRow>[0][],
  ) => void;
  /** Restores the approvals a paused run still waits for. */
  hydrateApprovals: (conversationId: string, rows: readonly AgentApprovalRow[]) => void;
  /** Appends an optimistic user message and returns its local id. */
  addUserMessage: (conversationId: string, content: string) => string;
  /**
   * Rewrites one user message and drops everything after it.
   *
   * The server performs the same truncation before the regenerated run, so the
   * optimistic transcript and the persisted one agree once it streams.
   */
  editUserMessage: (conversationId: string, messageId: string, content: string) => void;
  /** Marks the conversation as streaming; the answer arrives as events. */
  beginRun: (conversationId: string, input?: BeginRunInput) => void;
  /** Applies one streamed event. */
  applyEvent: (conversationId: string, event: AgentEvent) => void;
  /** Marks the answer as interrupted after the caller stopped the stream. */
  interrupt: (conversationId: string) => void;
  /**
   * Releases a run the client can no longer follow.
   *
   * Used when the server refuses a decision because it is already recorded: the
   * cards are gone and the next hydration restores the run's real state.
   */
  settleRun: (conversationId: string) => void;
  /** Records a failed stream that never reached the server. */
  failRun: (conversationId: string, message: string) => void;
  /** Records whether one message shows its thinking and tool calls. */
  setStepsCollapsed: (messageId: string, collapsed: boolean) => void;
  /** Removes a card the server refused to accept as a decision. */
  dropApproval: (conversationId: string, approvalId: string) => void;
  /** Opens or closes the floating widget. */
  setWidgetOpen: (open: boolean) => void;
}

/**
 * Agent store shared by the floating widget and the full page.
 *
 * Both surfaces read the same conversation id and the same transcripts, so a
 * message typed into the widget is already on screen when the page opens.
 */
export const useAgentStore = create<AgentState>()((set, get) => ({
  conversations: [],
  activeConversationId: null,
  transcripts: {},
  collapsedOverrides: {},
  widgetOpen: false,
  autoApprove: readAutoApprove(),
  pendingProviderId: readPendingProvider(),

  setAutoApprove: (enabled) => {
    try {
      globalThis.localStorage.setItem(AUTO_APPROVE_KEY, enabled ? '1' : '0');
    } catch {
      // Ignore: the switch still works without persistence.
    }
    set({ autoApprove: enabled });
  },

  setPendingProvider: (providerId) => {
    try {
      if (providerId === null) {
        globalThis.localStorage.removeItem(PENDING_PROVIDER_KEY);
      } else {
        globalThis.localStorage.setItem(PENDING_PROVIDER_KEY, providerId);
      }
    } catch {
      // Ignore: the choice still applies to this session.
    }
    set({ pendingProviderId: providerId });
  },

  setConversations: (conversations) => {
    set({ conversations });
  },

  upsertConversation: (conversation) => {
    set((state) => {
      const others = state.conversations.filter(
        (item) => item.conversation_id !== conversation.conversation_id,
      );
      return { conversations: [conversation, ...others] };
    });
  },

  removeConversation: (conversationId) => {
    set((state) => {
      const transcripts = { ...state.transcripts };
      const removed = transcripts[conversationId];
      delete transcripts[conversationId];
      const collapsedOverrides = { ...state.collapsedOverrides };
      for (const message of removed?.messages ?? []) {
        delete collapsedOverrides[message.messageId];
      }
      return {
        conversations: state.conversations.filter(
          (item) => item.conversation_id !== conversationId,
        ),
        activeConversationId:
          state.activeConversationId === conversationId ? null : state.activeConversationId,
        transcripts,
        collapsedOverrides,
      };
    });
  },

  setActiveConversation: (conversationId) => {
    set({ activeConversationId: conversationId });
  },

  hydrateMessages: (conversationId, rows) => {
    const current = get().transcripts[conversationId] ?? emptyTranscript();
    if (current.run.status === 'streaming') {
      // Tokens are arriving: the rows would drop the half-written answer.
      return;
    }
    if (current.run.status === 'awaiting_approval' && current.messages.length > 0) {
      // The paused answer only lives in this transcript (it is persisted when the
      // run ends), and its cards are already here.
      return;
    }
    set((state) => ({
      transcripts: {
        ...state.transcripts,
        [conversationId]: {
          ...emptyTranscript(),
          messages: rows.map(messageFromRow),
          run: current.run,
          approvals: current.approvals,
        },
      },
    }));
  },

  hydrateApprovals: (conversationId, rows) => {
    set((state) => {
      const transcript = state.transcripts[conversationId] ?? emptyTranscript();
      if (transcript.run.status === 'streaming') {
        // The live stream owns the cards of the run it is producing.
        return state;
      }
      const pending: AgentApproval[] = rows.map((row) => ({
        approvalId: row.approval_id,
        runId: row.run_id,
        tool: row.tool,
        argsHash: row.args_hash,
        reason: row.reason,
        status:
          row.status === 'approved' ? 'approved' : row.status === 'denied' ? 'denied' : 'pending',
      }));
      const waiting = new Set(pending.map((item) => item.approvalId));
      // The server only offers what still waits for a decision, so a card it does
      // not offer is settled (or its run is gone). A settled card stays as a
      // trace; one that was still pending here is dropped, or the chat would ask
      // again for a decision that is already recorded.
      const settled = transcript.approvals.filter(
        (item) => item.status !== 'pending' && !waiting.has(item.approvalId),
      );
      const approvals = [...settled, ...pending];
      if (
        approvals.length === transcript.approvals.length &&
        approvals.every((item, index) => item === transcript.approvals[index]) &&
        (pending.length > 0 || transcript.run.status !== 'awaiting_approval')
      ) {
        return state;
      }
      return {
        transcripts: {
          ...state.transcripts,
          [conversationId]: {
            ...transcript,
            approvals,
            run: {
              ...transcript.run,
              runId: pending[0]?.runId ?? transcript.run.runId,
              status:
                pending.length > 0
                  ? 'awaiting_approval'
                  : transcript.run.status === 'awaiting_approval'
                    ? 'completed'
                    : transcript.run.status,
            },
          },
        },
      };
    });
  },

  addUserMessage: (conversationId, content) => {
    const messageId = crypto.randomUUID();
    const message: AgentMessage = {
      messageId,
      role: 'user',
      content,
      createdAt: new Date().toISOString(),
      interrupted: false,
      tools: [],
      steps: [],
      resources: [],
      streaming: false,
      reasoning: '',
      stepsCollapsed: false,
      streamStartedAt: null,
      answerStartedAt: null,
      completedAt: null,
    };
    set((state) => {
      const transcript = state.transcripts[conversationId] ?? emptyTranscript();
      return {
        transcripts: {
          ...state.transcripts,
          [conversationId]: appendUserMessage(transcript, message),
        },
      };
    });
    return messageId;
  },

  editUserMessage: (conversationId, messageId, content) => {
    set((state) => {
      const transcript = state.transcripts[conversationId];
      if (transcript === undefined) {
        return state;
      }
      const index = transcript.messages.findIndex((message) => message.messageId === messageId);
      if (index < 0 || transcript.messages[index]?.role !== 'user') {
        return state;
      }
      const next = cloneTranscript(transcript);
      const removed = next.messages.slice(index + 1);
      const target = next.messages[index];
      if (target === undefined) {
        return state;
      }
      next.messages = next.messages.slice(0, index + 1);
      next.messages[index] = { ...target, content };
      next.approvals = [];
      next.run = { runId: null, status: 'idle', error: null, streamingMessageId: null };
      const collapsedOverrides = { ...state.collapsedOverrides };
      for (const message of removed) {
        delete collapsedOverrides[message.messageId];
      }
      return {
        transcripts: { ...state.transcripts, [conversationId]: next },
        collapsedOverrides,
      };
    });
  },

  beginRun: (conversationId, input) => {
    set((state) => {
      const transcript = state.transcripts[conversationId] ?? emptyTranscript();
      // A resume continues the run it paused on, so it keeps writing to the same
      // assistant message and keeps its approvals. A fresh prompt starts a new
      // run, and the cards of the previous one must not survive: answering them
      // would target a run that no longer waits for a decision.
      const resuming = input?.runId != null && input.runId === transcript.run.runId;
      const continued = resuming
        ? unfoldSteps(cloneTranscript(transcript), transcript.run.streamingMessageId)
        : transcript;
      const overrides = { ...state.collapsedOverrides };
      if (resuming && transcript.run.streamingMessageId !== null) {
        // A resume unfolds the trace of the message it keeps writing to, and the
        // fold choice of the reader must not keep it shut.
        delete overrides[transcript.run.streamingMessageId];
      }
      return {
        collapsedOverrides: overrides,
        transcripts: {
          ...state.transcripts,
          [conversationId]: {
            ...continued,
            approvals: resuming ? transcript.approvals : [],
            run: {
              runId: input?.runId ?? transcript.run.runId,
              status: 'streaming',
              error: null,
              streamingMessageId: resuming ? transcript.run.streamingMessageId : null,
            },
          },
        },
      };
    });
  },

  applyEvent: (conversationId, event) => {
    set((state) => {
      const transcript = state.transcripts[conversationId] ?? emptyTranscript();
      // The reducer mutates; publishing a copy is what makes React render the
      // token that just arrived.
      return {
        transcripts: {
          ...state.transcripts,
          [conversationId]: applyAgentEvent(cloneTranscript(transcript), event),
        },
      };
    });
  },

  interrupt: (conversationId) => {
    set((state) => {
      const transcript = state.transcripts[conversationId];
      if (transcript === undefined) {
        return state;
      }
      return {
        transcripts: {
          ...state.transcripts,
          [conversationId]: markInterrupted(cloneTranscript(transcript)),
        },
      };
    });
  },

  failRun: (conversationId, message) => {
    set((state) => {
      const transcript = state.transcripts[conversationId] ?? emptyTranscript();
      return {
        transcripts: {
          ...state.transcripts,
          [conversationId]: {
            ...transcript,
            run: { ...transcript.run, status: 'failed', error: message },
          },
        },
      };
    });
  },

  settleRun: (conversationId) => {
    set((state) => {
      const transcript = state.transcripts[conversationId];
      if (transcript === undefined) {
        return state;
      }
      return {
        transcripts: {
          ...state.transcripts,
          [conversationId]: {
            ...transcript,
            run: { ...transcript.run, status: 'idle', error: null, streamingMessageId: null },
          },
        },
      };
    });
  },

  setStepsCollapsed: (messageId, collapsed) => {
    set((state) => ({
      collapsedOverrides: { ...state.collapsedOverrides, [messageId]: collapsed },
    }));
  },

  dropApproval: (conversationId, approvalId) => {
    set((state) => {
      const transcript = state.transcripts[conversationId];
      if (transcript === undefined) {
        return state;
      }
      return {
        transcripts: {
          ...state.transcripts,
          [conversationId]: {
            ...transcript,
            approvals: transcript.approvals.filter((item) => item.approvalId !== approvalId),
          },
        },
      };
    });
  },

  setWidgetOpen: (open) => {
    set({ widgetOpen: open });
  },
}));

/**
 * Reads the transcript of one conversation.
 *
 * @param conversationId Id of the conversation, or `null`.
 * @returns The transcript, or the shared empty one so callers never guard.
 */
export function useTranscript(conversationId: string | null): AgentTranscript {
  return (
    useAgentStore((state) =>
      conversationId === null ? undefined : state.transcripts[conversationId],
    ) ?? EMPTY_TRANSCRIPT
  );
}

/**
 * Reads the conversation both surfaces show.
 *
 * @returns The active conversation, or `null` for a fresh chat.
 */
export function useActiveConversation(): AgentConversation | null {
  return (
    useAgentStore((state) =>
      state.conversations.find((item) => item.conversation_id === state.activeConversationId),
    ) ?? null
  );
}

/**
 * Reads the lifecycle status of the run a conversation shows.
 *
 * @param conversationId Id of the conversation, or `null`.
 * @returns The status, or `null` when the conversation was never opened.
 */
export function useRunStatus(conversationId: string | null): AgentRunStatus | null {
  return useAgentStore((state) =>
    conversationId === null ? null : (state.transcripts[conversationId]?.run.status ?? null),
  );
}

/**
 * Reads whether the active conversation is streaming.
 *
 * @param conversationId Id of the conversation, or `null`.
 * @returns `true` while tokens arrive or an approval waits.
 */
export function useIsRunning(conversationId: string | null): boolean {
  return useAgentStore((state) => {
    const status =
      conversationId === null ? undefined : state.transcripts[conversationId]?.run.status;
    return status === 'streaming' || status === 'awaiting_approval';
  });
}

/**
 * Reads and toggles the fold of one message's thinking and tool calls.
 *
 * The message carries what the reducer decided; a toggle of the user wins and
 * survives later streamed updates, because it is stored apart from the message.
 *
 * @param message Message whose steps are shown or folded.
 * @returns The effective fold and the toggle the summary button calls.
 */
export function useStepsCollapsed(message: AgentMessage): {
  collapsed: boolean;
  toggle: () => void;
} {
  const override = useAgentStore((state) => state.collapsedOverrides[message.messageId]);
  const setStepsCollapsed = useAgentStore((state) => state.setStepsCollapsed);
  const collapsed = override ?? message.stepsCollapsed;

  return {
    collapsed,
    toggle: () => {
      setStepsCollapsed(message.messageId, !collapsed);
    },
  };
}
