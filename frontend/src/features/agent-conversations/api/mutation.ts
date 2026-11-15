import { useMutation, useQueryClient } from '@tanstack/react-query';

import {
  agentKeys,
  discardConversation,
  patchConversation,
  useAgentStore,
  type AgentConversation,
} from '@/entities/agent';

/**
 * Renames a conversation.
 *
 * The store is updated before the refetch so both surfaces show the new title
 * immediately.
 *
 * @returns The rename mutation.
 */
export function useRenameConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { conversation: AgentConversation; title: string }) =>
      patchConversation(input.conversation.conversation_id, { title: input.title }),
    onSuccess: async (_result, input) => {
      useAgentStore.getState().upsertConversation({
        ...input.conversation,
        title: input.title.trim(),
      });
      await queryClient.invalidateQueries({ queryKey: agentKeys.conversations() });
    },
  });
}

/**
 * Discards a conversation.
 *
 * The store forgets the conversation right away and the refetch runs in the
 * background: awaiting it would delay the caller's own success handler, which is
 * what navigates away from the dead URL.
 *
 * @returns The discard mutation.
 */
export function useDiscardConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (conversationId: string) => discardConversation(conversationId),
    onSuccess: (_result, conversationId) => {
      useAgentStore.getState().removeConversation(conversationId);
      void queryClient.invalidateQueries({ queryKey: agentKeys.conversations() });
    },
  });
}
