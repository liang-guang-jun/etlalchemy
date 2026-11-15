import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';

import { useAgentStore } from '../model/store';
import {
  fetchConversations,
  fetchMessages,
  fetchPendingApprovals,
  fetchProviders,
} from './fetchers';
import { agentKeys } from './keys';

/**
 * Lists the conversations of the caller.
 *
 * @returns The query result of `GET /agent/conversations`.
 */
export function useConversations() {
  return useQuery({
    queryKey: agentKeys.conversations(),
    queryFn: () => fetchConversations(),
    // The list is small and changes on every run; a stale window keeps the
    // sidebar current after a message without polling.
    staleTime: 5_000,
  });
}

/**
 * Reads the messages of a conversation.
 *
 * An empty id disables the query, so the hook is safe before a conversation is
 * selected.
 *
 * @param conversationId Id of the conversation.
 * @returns The query result of `GET /agent/conversations/{id}/messages`.
 */
export function useConversationMessages(conversationId: string | null) {
  return useQuery({
    queryKey: agentKeys.messages(conversationId ?? ''),
    queryFn: () => fetchMessages(conversationId ?? ''),
    enabled: conversationId !== null && conversationId !== '',
  });
}

/**
 * Lists the LLM providers the caller may select.
 *
 * @returns The query result of `GET /agent/llm-providers`.
 */
export function useAgentProviders() {
  return useQuery({
    queryKey: agentKeys.providers(),
    queryFn: fetchProviders,
    staleTime: 60_000,
  });
}

/**
 * Lists the conversations and mirrors them into the shared store.
 *
 * Both the floating widget and the page call it, so the two surfaces always
 * render the same history without either passing props to the other.
 *
 * @returns The query result of `GET /agent/conversations`.
 */
export function useConversationFeed() {
  const query = useConversations();
  const rows = query.data;

  useEffect(() => {
    if (rows !== undefined) {
      useAgentStore.getState().setConversations(rows);
    }
  }, [rows]);

  return query;
}

/**
 * Reads the approvals of a conversation that still wait for a decision.
 *
 * @param conversationId Id of the conversation.
 * @returns The query result of `GET /agent/conversations/{id}/approvals`.
 */
export function usePendingApprovals(conversationId: string | null) {
  return useQuery({
    queryKey: agentKeys.approvals(conversationId ?? ''),
    queryFn: () => fetchPendingApprovals(conversationId ?? ''),
    enabled: conversationId !== null && conversationId !== '',
  });
}

/**
 * Loads the persisted messages of a conversation into the shared store.
 *
 * The store ignores the rows while a stream is open, so a refetch that lands
 * mid-answer cannot drop the half-written message. A paused run is restored the
 * same way: its cards come back from the pending approvals, so a reload does
 * not force the user to replay the stream.
 *
 * @param conversationId Id of the conversation, or `null`.
 * @returns The query result of `GET /agent/conversations/{id}/messages`.
 */
export function useConversationHydration(conversationId: string | null) {
  const query = useConversationMessages(conversationId);
  const rows = query.data;
  const approvals = usePendingApprovals(conversationId);
  const pending = approvals.data;

  useEffect(() => {
    if (conversationId !== null && conversationId !== '' && rows !== undefined) {
      useAgentStore.getState().hydrateMessages(conversationId, rows);
    }
  }, [conversationId, rows]);

  useEffect(() => {
    if (conversationId !== null && conversationId !== '' && pending !== undefined) {
      useAgentStore.getState().hydrateApprovals(conversationId, pending);
    }
  }, [conversationId, pending]);

  return query;
}
