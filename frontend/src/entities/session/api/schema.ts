import { z } from 'zod';

/** Response of every login, refresh and current-session endpoint. */
export const sessionResponseSchema = z.object({
  access_token: z.string(),
  token_type: z.string(),
  session_id: z.string(),
  identity_id: z.string(),
  user_id: z.string(),
  tenant_id: z.string().nullable(),
  expires_at: z.string(),
  refresh_at: z.string(),
});

export type SessionResponse = z.infer<typeof sessionResponseSchema>;

/** Body of `POST /iam/auth/password`. */
export const passwordLoginSchema = z.object({
  login: z.string().min(1, 'Enter your username or email'),
  password: z.string().min(1, 'Enter your password'),
  tenant_id: z.string().optional(),
});

export type PasswordLogin = z.infer<typeof passwordLoginSchema>;

/** Body of `POST /iam/auth/api-key`. */
export const apiKeyLoginSchema = z.object({
  api_key: z.string().min(1, 'Enter your API key'),
});

export type ApiKeyLogin = z.infer<typeof apiKeyLoginSchema>;

/** Response of `GET /iam/bootstrap`. */
export const bootstrapStatusSchema = z.object({
  completed: z.boolean(),
});

export type BootstrapStatus = z.infer<typeof bootstrapStatusSchema>;
