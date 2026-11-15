import { Navigate } from 'react-router';

import { useSessionStore } from '@/entities/session';
import { LoginForm } from '@/features/auth-login';

/**
 * Renders the login form, or the catalog when a session is already stored.
 *
 * @returns The login page content.
 */
export default function LoginPage() {
  const accessToken = useSessionStore((state) => state.accessToken);
  if (accessToken !== null) {
    return <Navigate to="/catalog" replace />;
  }
  return <LoginForm />;
}
