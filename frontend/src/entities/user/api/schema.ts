import { z } from 'zod';

/** A user as returned by the IAM read model. */
export const userResponseSchema = z.object({
  user_id: z.string(),
  username: z.string(),
  email: z.string(),
  display_name: z.string(),
  status: z.string(),
  is_system_admin: z.boolean(),
});

export type UserResponse = z.infer<typeof userResponseSchema>;

/** A user reduced to what an `@` mention needs. */
export const userSummarySchema = z.object({
  user_id: z.string(),
  username: z.string(),
  display_name: z.string(),
});

export type UserSummary = z.infer<typeof userSummarySchema>;
