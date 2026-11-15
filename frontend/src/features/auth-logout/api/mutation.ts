import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router';

import { logoutSession, useSessionStore } from '@/entities/session';

/**
 * Revokes the session and clears the local store.
 *
 * Revocation is applied by the projection, so the token may keep working for a
 * moment; clearing the store is what signs the user out locally.
 *
 * @returns The mutation result.
 */
export function useLogout() {
  const navigate = useNavigate();

  return useMutation({
    mutationFn: logoutSession,
    onSettled: () => {
      useSessionStore.getState().clear();
      void navigate('/login', { replace: true });
    },
  });
}
