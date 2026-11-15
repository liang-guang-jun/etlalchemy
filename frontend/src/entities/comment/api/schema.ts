import { z } from 'zod';

/** A discussion thread of the read model. */
export const threadSchema = z.object({
  thread_id: z.string(),
  target_type: z.string(),
  target_id: z.string(),
  title: z.string(),
  status: z.string(),
  author_user_id: z.string(),
  author_tenant_id: z.string().nullable(),
  comment_count: z.number(),
  last_activity_at: z.string(),
  created_at: z.string(),
  resolved_at: z.string().nullable(),
  resolved_by: z.string().nullable(),
});

export type Thread = z.infer<typeof threadSchema>;

/** One comment of a thread. */
export const commentSchema = z.object({
  comment_id: z.string(),
  thread_id: z.string(),
  parent_comment_id: z.string().nullable(),
  author_user_id: z.string(),
  author_tenant_id: z.string().nullable(),
  body: z.string(),
  mentions: z.array(z.string()),
  created_at: z.string(),
  edited_at: z.string().nullable(),
  discarded_at: z.string().nullable(),
  depth: z.number(),
});

export type Comment = z.infer<typeof commentSchema>;

/** A thread together with its comments, oldest first. */
export const threadDetailSchema = z.object({
  thread: threadSchema,
  comments: z.array(commentSchema),
});

export type ThreadDetail = z.infer<typeof threadDetailSchema>;

/** Body of `POST /comments/threads`. */
export const threadCreateSchema = z.object({
  target_type: z.string().min(1, 'Pick a target type'),
  target_id: z.string().min(1, 'Pick a target'),
  title: z.string().optional(),
  body: z.string().trim().min(1, 'Write something first'),
  mentions: z.array(z.string()).max(20, 'Mention at most 20 people'),
});

export type ThreadCreate = z.infer<typeof threadCreateSchema>;

/** Body of `POST /comments/threads/{thread_id}/comments`. */
export const commentCreateSchema = z.object({
  body: z.string().trim().min(1, 'Write something first'),
  parent_comment_id: z.string().nullable().optional(),
  mentions: z.array(z.string()).max(20, 'Mention at most 20 people'),
});

export type CommentCreate = z.infer<typeof commentCreateSchema>;

/** Body of `PATCH .../comments/{comment_id}`. */
export const commentEditSchema = z.object({
  body: z.string().trim().min(1, 'Write something first').optional(),
  mentions: z.array(z.string()).max(20, 'Mention at most 20 people').optional(),
});

export type CommentEdit = z.infer<typeof commentEditSchema>;

/** Result of `POST /comments/threads`. */
export const threadCreatedSchema = z.object({
  thread_id: z.string(),
  root_comment_id: z.string(),
});

export type ThreadCreated = z.infer<typeof threadCreatedSchema>;

/** Result of `POST /comments/threads/{thread_id}/comments`. */
export const commentCreatedSchema = z.object({
  comment_id: z.string(),
  depth: z.number(),
  depth_warning: z.string().nullable(),
});

export type CommentCreated = z.infer<typeof commentCreatedSchema>;

/** What the backend knows about a comment target. */
export const targetDescriptionSchema = z.object({
  target_type: z.enum([
    'catalog',
    'schema',
    'table',
    'field',
    'semantic_model',
    'semantic_entity',
    'relationship',
    'term',
    'domain',
    'ingestion_connection',
    'import_run',
  ]),
  target_id: z.string(),
  name: z.string(),
  path: z.string(),
  catalog_id: z.string().nullable(),
  schema_name: z.string().nullable(),
  table_name: z.string().nullable(),
  field_name: z.string().nullable(),
  model_id: z.string().nullable(),
  entity_name: z.string().nullable(),
  domain_id: z.string().nullable(),
});
