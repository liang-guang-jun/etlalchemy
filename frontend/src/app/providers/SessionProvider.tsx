import { useEffect, type ReactNode } from 'react';

import { useSessionRefresh, useSessionStore } from '@/entities/session';
import { useUser } from '@/entities/user';

export interface SessionProviderProps {
  children: ReactNode;
}

/**
 * Keeps the stored session in sync with the server.
 *
 * It fills the `is_system_admin` flag of the signed-in user (the session
 * response does not carry it) and schedules the silent refresh.
 *
 * @param props Component props.
 * @returns The children once the session is hydrated.
 */
export function SessionProvider({ children }: SessionProviderProps) {
  const accessToken = useSessionStore((state) => state.accessToken);
  const userId = useSessionStore((state) => state.userId);
  const user = useSessionStore((state) => state.user);
  const setUser = useSessionStore((state) => state.setUser);

  const { data } = useUser(accessToken !== null && user === null ? userId : null);

  useEffect(() => {
    if (data !== undefined) {
      setUser(data);
    }
  }, [data, setUser]);

  useSessionRefresh();

  return <>{children}</>;
}
