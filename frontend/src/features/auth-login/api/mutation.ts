import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router';

import {
  loginWithApiKey,
  loginWithPassword,
  toSnapshot,
  useSessionStore,
  type ApiKeyLogin,
  type PasswordLogin,
} from '@/entities/session';

/**
 * Signs in with a login and password and stores the session.
 *
 * @returns The mutation result.
 */
export function usePasswordLogin() {
  const setSession = useSessionStore((state) => state.setSession);
  const navigate = useNavigate();

  return useMutation({
    mutationFn: (body: PasswordLogin) => loginWithPassword(body),
    onSuccess: (session) => {
      useSessionStore.getState().clear();
      setSession(toSnapshot(session));
      void navigate('/catalog', { replace: true });
    },
  });
}

/**
 * Signs in with an API key and stores the session.
 *
 * @returns The mutation result.
 */
export function useApiKeyLogin() {
  const setSession = useSessionStore((state) => state.setSession);
  const navigate = useNavigate();

  return useMutation({
    mutationFn: (body: ApiKeyLogin) => loginWithApiKey(body),
    onSuccess: (session) => {
      useSessionStore.getState().clear();
      setSession(toSnapshot(session));
      void navigate('/catalog', { replace: true });
    },
  });
}
