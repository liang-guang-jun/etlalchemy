import { Link } from 'react-router';

import { Button, EmptyState } from '@/shared/ui';

/**
 * Renders the 404 page.
 *
 * @returns The not-found page.
 */
export default function NotFoundPage() {
  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <EmptyState
        title="Page not found"
        description="Check the address or return to the data catalog."
        action={
          <Link to="/catalog">
            <Button>Back to data catalog</Button>
          </Link>
        }
      />
    </div>
  );
}
