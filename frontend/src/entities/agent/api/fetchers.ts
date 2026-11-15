import { client } from '@/shared/api/client';

import {
  approvalSchema,
  conversationSchema,
  messageSchema,
  providerSchema,
  runSchema,
  type AgentApprovalRow,
  type AgentConversation,
  type AgentMessageRow,
  type AgentProvider,
  type AgentRunRow,
} from './schema';

/**
 * Lists the conversations of the caller, most recent first.
 *
 * @param limit Maximum number of rows.
 * @returns The conversation rows.
 */
export async function fetchConversations(limit?: number): Promise<AgentConversation[]> {
  const response = await client.get('/agent/conversations', { params: { limit } });
  return conversationSchema.array().parse(response.data);
}

/**
 * Reads one conversation.
 *
 * @param conversationId Id of the conversation.
 * @returns The conversation row.
 */
export async function fetchConversation(conversationId: string): Promise<AgentConversation> {
  const response = await client.get(`/agent/conversations/${conversationId}`);
  return conversationSchema.parse(response.data);
}

/**
 * Starts a conversation.
 *
 * @param body Optional title and provider.
 * @returns The created conversation.
 */
export async function createConversation(body: {
  title?: string;
  llmProviderId?: string | null;
}): Promise<AgentConversation> {
  const response = await client.post('/agent/conversations', {
    title: body.title ?? '',
    llm_provider_id: body.llmProviderId ?? null,
  });
  return conversationSchema.parse(response.data);
}

/**
 * Renames a conversation or switches its provider.
 *
 * @param conversationId Id of the conversation.
 * @param body Fields to change; omitted fields are left alone.
 * @returns Nothing; the list is refetched by the caller.
 */
export async function patchConversation(
  conversationId: string,
  body: { title?: string; llmProviderId?: string },
): Promise<void> {
  await client.patch(`/agent/conversations/${conversationId}`, {
    title: body.title,
    llm_provider_id: body.llmProviderId,
  });
}

/**
 * Discards a conversation.
 *
 * @param conversationId Id of the conversation.
 * @returns Nothing.
 */
export async function discardConversation(conversationId: string): Promise<void> {
  await client.delete(`/agent/conversations/${conversationId}`);
}

/**
 * Reads the messages of a conversation, oldest first.
 *
 * @param conversationId Id of the conversation.
 * @returns The message rows with their tool and resource traces.
 */
export async function fetchMessages(conversationId: string): Promise<AgentMessageRow[]> {
  const response = await client.get(`/agent/conversations/${conversationId}/messages`);
  return messageSchema.array().parse(response.data);
}

/**
 * Lists the LLM providers the caller may select.
 *
 * @returns The provider rows.
 */
export async function fetchProviders(): Promise<AgentProvider[]> {
  const response = await client.get('/agent/llm-providers');
  return providerSchema.array().parse(response.data);
}

/**
 * Reads one run with its approvals.
 *
 * @param runId Id of the run.
 * @returns The run row.
 */
export async function fetchRun(runId: string): Promise<AgentRunRow> {
  const response = await client.get(`/agent/runs/${runId}`);
  return runSchema.parse(response.data);
}

/**
 * Lists the approvals of a conversation that still wait for a decision.
 *
 * @param conversationId Id of the conversation.
 * @returns The pending approval rows.
 */
export async function fetchPendingApprovals(conversationId: string): Promise<AgentApprovalRow[]> {
  const response = await client.get(`/agent/conversations/${conversationId}/approvals`);
  return approvalSchema.array().parse(response.data);
}
