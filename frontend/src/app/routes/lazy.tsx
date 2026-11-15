import { lazy, Suspense, type ComponentType, type ReactElement } from 'react';

import { Skeleton } from '@/shared/ui';

/**
 * Wraps a lazily imported page component in a Suspense boundary.
 *
 * @param load Dynamic import of the page module.
 * @returns The route element rendering that page.
 */
export function lazyPage(load: () => Promise<{ default: ComponentType }>): ReactElement {
  const Page = lazy(load);
  return (
    <Suspense
      fallback={
        <div className="p-6">
          <Skeleton lines={6} />
        </div>
      }
    >
      <Page />
    </Suspense>
  );
}
