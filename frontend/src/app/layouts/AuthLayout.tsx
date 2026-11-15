import { Outlet } from 'react-router';

import { Brand } from '@/shared/ui';

/**
 * Centred layout shared by the login and bootstrap pages.
 *
 * @returns The layout element with the routed page.
 */
export function AuthLayout() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-muted p-6">
      <div className="flex w-full max-w-md flex-col items-center gap-4">
        <Brand className="mb-1" />
        <Outlet />
      </div>
    </div>
  );
}
