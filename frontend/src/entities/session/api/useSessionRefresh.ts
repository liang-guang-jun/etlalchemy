import { useEffect } from 'react';

import { useSessionStore } from '../model/store';
import { refreshSession } from './fetchers';
import { toSnapshot } from '../model/snapshot';

/**
 * Refreshes the session shortly before it expires.
 *
 * The moment is taken from `refresh_at`, which the backend computes from
 * `iam.session_refresh_lead_minutes`, so the lead time lives in `config.*.yaml`
 * and not in the frontend. A failed refresh clears the session, and the auth
 * guard then sends the user to the login page.
 */
export function useSessionRefresh(): void {
  const accessToken = useSessionStore((state) => state.accessToken);
  const refreshAt = useSessionStore((state) => state.refreshAt);
  const setSession = useSessionStore((state) => state.setSession);
  const clear = useSessionStore((state) => state.clear);

  useEffect(() => {
    if (accessToken === null || refreshAt === null) {
      return undefined;
    }
    const delay = Math.max(new Date(refreshAt).getTime() - Date.now(), 1_000);
    const timer = window.setTimeout(() => {
      refreshSession()
        .then((session) => {
          setSession(toSnapshot(session));
        })
        .catch(() => {
          clear();
        });
    }, delay);
    return () => {
      window.clearTimeout(timer);
    };
  }, [accessToken, refreshAt, setSession, clear]);
}
