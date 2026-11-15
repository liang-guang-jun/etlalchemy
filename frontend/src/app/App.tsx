import { RouterProvider } from 'react-router';

import { ErrorBoundary } from '@/app/providers/ErrorBoundary';
import { MotionProvider } from '@/app/providers/MotionProvider';
import { QueryProvider } from '@/app/providers/QueryProvider';
import { SessionProvider } from '@/app/providers/SessionProvider';
import { ToastProvider } from '@/app/providers/ToastProvider';
import { router } from '@/app/routes/router';

/**
 * Root component: providers around the router.
 *
 * @returns The application tree.
 */
export function App() {
  return (
    <ErrorBoundary>
      <MotionProvider>
        <QueryProvider>
          <SessionProvider>
            <ToastProvider>
              <RouterProvider router={router} />
            </ToastProvider>
          </SessionProvider>
        </QueryProvider>
      </MotionProvider>
    </ErrorBoundary>
  );
}
