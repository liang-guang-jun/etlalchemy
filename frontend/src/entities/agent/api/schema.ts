import { z } from 'zod';

/** One conversation of the read model. */
export const conversationSchema = z.object({
  conversation_id: z.string(),
  user_id: z.string(),
  tenant_id: z.string().nullable(),
  title: z.string(),
  status: z.string(),
  active_llm_provider_id: z.string().nullable(),
  message_count: z.number(),
  run_count: z.number(),
  created_at: z.string(),
  last_activity_at: z.string(),
});

export type AgentConversation = z.infer<typeof conversationSchema>;

/** One MCP tool call recorded on a message. */
export const toolCallSchema = z.object({
  tool: z.string(),
  args_hash: z.string(),
  status: z.string(),
  duration_ms: z.number(),
  error_code: z.string().nullable(),
  args_json: z.string().default(''),
  result_preview: z.string().default(''),
});

/** One MCP resource read recorded on a message. */
export const resourceAccessSchema = z.object({
  uri: z.string(),
  size_bytes: z.number(),
  mime_type: z.string(),
  read_at: z.string().nullable().optional(),
});

/** One message of a conversation. */
export const messageSchema = z.object({
  message_id: z.string(),
  conversation_id: z.string(),
  role: z.string(),
  content: z.string(),
  interrupted: z.boolean(),
  input_tokens: z.number(),
  output_tokens: z.number(),
  created_at: z.string(),
  resources: z.array(resourceAccessSchema),
  tools: z.array(toolCallSchema),
  reasoning: z.string().default(''),
});

export type AgentMessageRow = z.infer<typeof messageSchema>;

/** One LLM provider the caller may use. */
export const providerSchema = z.object({
  provider_id: z.string(),
  name: z.string(),
  kind: z.string(),
  endpoint: z.string().nullable(),
  credential_ref: z.string().nullable(),
  has_inline_credential: z.boolean(),
  default_model: z.string(),
  options: z.record(z.string(), z.string()),
  owner_user_id: z.string(),
  tenant_id: z.string().nullable(),
  is_public: z.boolean(),
  is_system_default: z.boolean(),
  created_at: z.string(),
});

export type AgentProvider = z.infer<typeof providerSchema>;

/** One approval of a run. */
export const approvalSchema = z.object({
  approval_id: z.string(),
  run_id: z.string(),
  tool: z.string(),
  args_hash: z.string(),
  reason: z.string(),
  status: z.string(),
  requested_at: z.string(),
  decided_by: z.string().nullable().optional(),
  decided_at: z.string().nullable().optional(),
});

export type AgentApprovalRow = z.infer<typeof approvalSchema>;

/** One run with its approvals. */
export const runSchema = z.object({
  run_id: z.string(),
  conversation_id: z.string(),
  message_id: z.string(),
  status: z.string(),
  started_at: z.string(),
  finished_at: z.string().nullable().optional(),
  error: z.string().nullable().optional(),
  approvals: z.array(approvalSchema),
});

export type AgentRunRow = z.infer<typeof runSchema>;
