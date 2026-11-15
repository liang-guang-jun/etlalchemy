/** The signed-in user as returned by `GET /iam/users/{user_id}`. */
export interface SessionUser {
  user_id: string;
  username: string;
  email: string;
  display_name: string;
  status: string;
  is_system_admin: boolean;
}

/** The session fields persisted between page loads. */
export interface SessionSnapshot {
  accessToken: string;
  sessionId: string;
  identityId: string;
  userId: string;
  tenantId: string | null;
  expiresAt: string;
  refreshAt: string;
}
