import { useMutation, useQueryClient } from '@tanstack/react-query';

import {
  agentKeys,
  patchConversation,
  useAgentStore,
  type AgentConversation,
} from '@/entities/agent';

/**
 * Switches the LLM a conversation uses.
 *
 * The store is updated before the refetch so the header shows the new model
 * while the request is still in flight.
 *
 * @returns The switch mutation.
 */
export function useSwitchProvider() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { conversation: AgentConversation; providerId: string }) =>
      patchConversation(input.conversation.conversation_id, {
        llmProviderId: input.providerId,
      }),
    onSuccess: async (_result, input) => {
      useAgentStore.getState().upsertConversation({
        ...input.conversation,
        active_llm_provider_id: input.providerId,
      });
      await queryClient.invalidateQueries({ queryKey: agentKeys.conversations() });
    },
  });
}
