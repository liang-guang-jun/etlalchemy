import { useCallback, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import {
  agentKeys,
  createConversation,
  streamAgentMessage,
  streamApprovalDecision,
  streamEditedMessage,
  useAgentStore,
  useIsRunning,
} from '@/entities/agent';
import { isAbortError } from '@/shared/api/sse';
import { normalizeError, type ApiError } from '@/shared/api/error';

import { abortStream, beginStream, releaseStream } from './controllers';

/** Options of {@link useAgentChat}. */
export interface AgentChatOptions {
  /**
   * Called when a prompt created a conversation because none was selected.
   *
   * The page uses it to move the URL to `/agent/{id}`, the widget ignores it.
   */
  onConversationCreated?: (conversationId: string) => void;
}

/** Options of {@link AgentChatController.send}. */
export interface SendOptions {
  /**
   * Page the reader has open, forwarded to the server as `page_context`.
   *
   * The server splices it into the system prompt, so the agent knows which
   * catalog, schema or table "these" means while the transcript keeps the typed
   * text alone.
   */
  pageContext?: string | null;
}

/** Commands the chat surfaces share. */
export interface AgentChatController {
  /** Sends a prompt, starting a conversation when none is selected. */
  send: (content: string, options?: SendOptions) => Promise<void>;
  /**
   * Rewrites a user message and regenerates the answer.
   *
   * Every message after the edited one is dropped first, on the server and in
   * the transcript, so the new answer replaces the old tail.
   */
  edit: (messageId: string, content: string, options?: SendOptions) => Promise<void>;
  /** Answers an approval and streams the rest of the run. */
  decide: (approvalId: string, approved: boolean) => Promise<void>;
  /** Aborts the running stream. */
  stop: () => void;
  /** Whether the conversation runs or waits for an approval. */
  running: boolean;
  /** Failure of the last attempt, or `null`. */
  error: string | null;
}

/** Longest title derived from a first prompt. */
const DERIVED_TITLE_LENGTH = 80;

/**
 * Detects a decision the server already holds.
 *
 * A resumed run replays the approval it paused on, and a second browser tab may
 * answer the same card first. Both answer `409` with `approval <id> is already
 * <status>`, which is not a failure the reader has to see.
 *
 * @param failure Normalised error of a failed decision.
 * @returns `true` when the approval was already decided.
 */
function isDecidedApproval(failure: ApiError): boolean {
  return failure.status === 409 && /^approval \S+ is already /.test(failure.detail);
}

/**
 * Derives a conversation title from the first prompt.
 *
 * @param content Prompt text.
 * @returns A single line, cut to {@link DERIVED_TITLE_LENGTH} characters.
 */
function deriveTitle(content: string): string {
  const line = content.replace(/\s+/g, ' ').trim();
  return line.length <= DERIVED_TITLE_LENGTH ? line : `${line.slice(0, DERIVED_TITLE_LENGTH - 1)}…`;
}

/**
 * Wires one surface to the shared agent store and the streaming endpoints.
 *
 * Every event the server sends is written into the store through
 * `applyEvent`, so the other surface (floating widget or full page) re-renders
 * without subscribing to anything else.
 *
 * @param conversationId Conversation the surface shows, or `null` for a new chat.
 * @param options Callback used when a prompt created a conversation.
 * @returns The commands of the surface.
 */
export function useAgentChat(
  conversationId: string | null,
  options: AgentChatOptions = {},
): AgentChatController {
  const queryClient = useQueryClient();
  const running = useIsRunning(conversationId);
  const onConversationCreated = options.onConversationCreated;
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(
    async (id: string) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: agentKeys.conversations() }),
        queryClient.invalidateQueries({ queryKey: agentKeys.messages(id) }),
        // A decision or a finished run changes what still waits, so a stale card
        // (a ``pending`` row of a run that is gone) disappears with it.
        queryClient.invalidateQueries({ queryKey: agentKeys.approvals(id) }),
      ]);
    },
    [queryClient],
  );

  const send = useCallback(
    async (content: string, options: SendOptions = {}) => {
      const prompt = content.trim();
      if (prompt === '') {
        return;
      }
      const pageContext = options.pageContext?.trim() ?? '';
      setError(null);
      let id = conversationId ?? useAgentStore.getState().activeConversationId;
      let providerForRun: string | null | undefined;
      if (id === null) {
        const pendingProviderId = useAgentStore.getState().pendingProviderId;
        try {
          const created = await createConversation({
            title: deriveTitle(prompt),
            llmProviderId: pendingProviderId,
          });
          useAgentStore.getState().upsertConversation(created);
          useAgentStore.getState().setActiveConversation(created.conversation_id);
          id = created.conversation_id;
          providerForRun = pendingProviderId;
          onConversationCreated?.(id);
        } catch (failure: unknown) {
          setError(normalizeError(failure).detail);
          return;
        }
      }
      const target = id;
      useAgentStore.getState().addUserMessage(target, prompt);
      useAgentStore.getState().beginRun(target);
      const autoApprove = useAgentStore.getState().autoApprove;
      const controller = beginStream(target);
      try {
        await streamAgentMessage({
          conversationId: target,
          content: prompt,
          llmProviderId: providerForRun,
          pageContext: pageContext === '' ? null : pageContext,
          autoApprove,
          signal: controller.signal,
          onEvent: (event) => {
            useAgentStore.getState().applyEvent(target, event);
          },
        });
      } catch (failure: unknown) {
        if (isAbortError(failure)) {
          useAgentStore.getState().interrupt(target);
        } else {
          const failed = normalizeError(failure);
          setError(failed.detail);
          useAgentStore.getState().failRun(target, failed.detail);
        }
      } finally {
        releaseStream(target, controller);
        await refresh(target);
      }
    },
    [conversationId, onConversationCreated, refresh],
  );

  const edit = useCallback(
    async (messageId: string, content: string, options: SendOptions = {}) => {
      const prompt = content.trim();
      const id = conversationId ?? useAgentStore.getState().activeConversationId;
      if (id === null || prompt === '') {
        return;
      }
      const pageContext = options.pageContext?.trim() ?? '';
      setError(null);
      useAgentStore.getState().editUserMessage(id, messageId, prompt);
      useAgentStore.getState().beginRun(id);
      const autoApprove = useAgentStore.getState().autoApprove;
      const controller = beginStream(id);
      try {
        await streamEditedMessage({
          conversationId: id,
          messageId,
          content: prompt,
          pageContext: pageContext === '' ? null : pageContext,
          autoApprove,
          signal: controller.signal,
          onEvent: (event) => {
            useAgentStore.getState().applyEvent(id, event);
          },
        });
      } catch (failure: unknown) {
        if (isAbortError(failure)) {
          useAgentStore.getState().interrupt(id);
        } else {
          const failed = normalizeError(failure);
          setError(failed.detail);
          useAgentStore.getState().failRun(id, failed.detail);
        }
      } finally {
        releaseStream(id, controller);
        await refresh(id);
      }
    },
    [conversationId, refresh],
  );

  const decide = useCallback(
    async (approvalId: string, approved: boolean) => {
      const id = conversationId;
      if (id === null) {
        return;
      }
      const transcript = useAgentStore.getState().transcripts[id];
      // The card carries the run that asked for the decision, which is not
      // necessarily the run the transcript currently shows.
      const approval = transcript?.approvals.find((item) => item.approvalId === approvalId);
      const runId = approval?.runId ?? transcript?.run.runId ?? null;
      if (runId === null) {
        return;
      }
      useAgentStore.getState().beginRun(id, { runId });
      const controller = beginStream(id);
      try {
        await streamApprovalDecision({
          runId,
          approvalId,
          approved,
          signal: controller.signal,
          onEvent: (event) => {
            useAgentStore.getState().applyEvent(id, event);
          },
        });
      } catch (failure: unknown) {
        if (isAbortError(failure)) {
          useAgentStore.getState().interrupt(id);
        } else {
          const failed = normalizeError(failure);
          // The server refused the decision (the run already moved on), so the
          // card cannot be answered any more; dropping it unlocks the composer
          // instead of letting the reader click it again.
          useAgentStore.getState().dropApproval(id, approvalId);
          if (isDecidedApproval(failed)) {
            // Already approved or denied: the answer, not an error, is what the
            // refusal means. The hydration below restores the run's real state.
            useAgentStore.getState().settleRun(id);
          } else {
            setError(failed.detail);
            useAgentStore.getState().failRun(id, failed.detail);
          }
        }
      } finally {
        releaseStream(id, controller);
        await refresh(id);
      }
    },
    [conversationId, refresh],
  );

  const stop = useCallback(() => {
    const id = conversationId ?? useAgentStore.getState().activeConversationId;
    if (id !== null) {
      abortStream(id);
    }
  }, [conversationId]);

  return { send, edit, decide, stop, running, error };
}
