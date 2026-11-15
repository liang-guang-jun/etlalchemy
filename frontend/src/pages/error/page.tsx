import { Link, useSearchParams } from 'react-router';

import { Button, EmptyState } from '@/shared/ui';

/**
 * Renders a generic failure page with the message from the query string.
 *
 * @returns The error page.
 */
export default function ErrorPage() {
  const [params] = useSearchParams();
  const message = params.get('message') ?? 'An unexpected error occurred.';

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <EmptyState
        title="Something went wrong"
        description={message}
        action={
          <Link to="/catalog">
            <Button>Back to data catalog</Button>
          </Link>
        }
      />
    </div>
  );
}
