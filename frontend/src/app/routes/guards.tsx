import type { ReactNode } from 'react';
import { Navigate } from 'react-router';

import { selectIsSystemAdmin, useSessionStore } from '@/entities/session';
import { EmptyState } from '@/shared/ui';

export interface GuardProps {
  children: ReactNode;
}

/**
 * Requires a stored session.
 *
 * @param props Component props.
 * @returns The protected children or a redirect to the login page.
 */
export function RequireAuth({ children }: GuardProps) {
  const accessToken = useSessionStore((state) => state.accessToken);
  if (accessToken === null) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

/**
 * Requires a signed-in system administrator.
 *
 * @param props Component props.
 * @returns The protected children, a loading state or a redirect.
 */
export function RequireAdmin({ children }: GuardProps) {
  const accessToken = useSessionStore((state) => state.accessToken);
  const isAdmin = useSessionStore(selectIsSystemAdmin);
  const hasUser = useSessionStore((state) => state.user !== null);

  if (accessToken === null) {
    return <Navigate to="/login" replace />;
  }
  if (!hasUser) {
    return <EmptyState title="Loading session" description="Please wait…" />;
  }
  if (!isAdmin) {
    return <Navigate to="/catalog" replace />;
  }
  return <>{children}</>;
}
