import { create } from 'zustand';
import { persist } from 'zustand/middleware';

import type { SessionSnapshot, SessionUser } from './types';

interface SessionState {
  accessToken: string | null;
  sessionId: string | null;
  identityId: string | null;
  userId: string | null;
  tenantId: string | null;
  expiresAt: string | null;
  refreshAt: string | null;
  user: SessionUser | null;
  setSession: (snapshot: SessionSnapshot) => void;
  setUser: (user: SessionUser) => void;
  clear: () => void;
}

const NO_SESSION = {
  accessToken: null,
  sessionId: null,
  identityId: null,
  userId: null,
  tenantId: null,
  expiresAt: null,
  refreshAt: null,
  user: null,
} satisfies Omit<SessionState, 'setSession' | 'setUser' | 'clear'>;

/**
 * Session store.
 *
 * The bearer token is kept in `localStorage` so a page reload keeps the user
 * signed in. Any script running in the page can read it, which is the accepted
 * trade-off documented in the README.
 */
export const useSessionStore = create<SessionState>()(
  persist(
    (set) => ({
      ...NO_SESSION,
      setSession: (snapshot) => {
        set({ ...snapshot });
      },
      setUser: (user) => {
        set({ user });
      },
      clear: () => {
        set({ ...NO_SESSION });
      },
    }),
    {
      name: 'etlalchemy.session',
      partialize: (state) => ({
        accessToken: state.accessToken,
        sessionId: state.sessionId,
        identityId: state.identityId,
        userId: state.userId,
        tenantId: state.tenantId,
        expiresAt: state.expiresAt,
        refreshAt: state.refreshAt,
        user: state.user,
      }),
    },
  ),
);

/** Selects whether a bearer token is currently stored. */
export function selectIsAuthenticated(state: SessionState): boolean {
  return state.accessToken !== null;
}

/** Selects whether the signed-in user is a system administrator. */
export function selectIsSystemAdmin(state: SessionState): boolean {
  return state.user?.is_system_admin === true;
}
