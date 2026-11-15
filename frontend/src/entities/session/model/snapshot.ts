import type { SessionResponse } from '../api/schema';
import type { SessionSnapshot } from './types';

/**
 * Maps a session response onto the fields persisted between page loads.
 *
 * @param session Response of a login, refresh or current-session call.
 * @returns The snapshot stored by the session store.
 */
export function toSnapshot(session: SessionResponse): SessionSnapshot {
  return {
    accessToken: session.access_token,
    sessionId: session.session_id,
    identityId: session.identity_id,
    userId: session.user_id,
    tenantId: session.tenant_id,
    expiresAt: session.expires_at,
    refreshAt: session.refresh_at,
  };
}
