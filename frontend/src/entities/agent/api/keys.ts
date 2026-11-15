/** Query keys of the agent entity. */
export const agentKeys = {
  all: ['agent'] as const,
  conversations: () => [...agentKeys.all, 'conversations'] as const,
  conversation: (conversationId: string) =>
    [...agentKeys.all, 'conversation', conversationId] as const,
  messages: (conversationId: string) => [...agentKeys.all, 'messages', conversationId] as const,
  approvals: (conversationId: string) => [...agentKeys.all, 'approvals', conversationId] as const,
  providers: () => [...agentKeys.all, 'providers'] as const,
  run: (runId: string) => [...agentKeys.all, 'run', runId] as const,
};
