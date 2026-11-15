import { useBootstrapStatus } from '@/entities/session';
import { ErrorState, Skeleton, Tooltip } from '@/shared/ui';

/**
 * Shows whether the deployment already has a system administrator.
 *
 * There is no HTTP endpoint that creates the first administrator, so the page
 * only reports the status and points at the CLI command.
 *
 * @returns The bootstrap status card.
 */
export function BootstrapStatusCard() {
  const { data, isPending, isError, error, refetch } = useBootstrapStatus();

  if (isPending) {
    return <Skeleton lines={4} />;
  }

  if (isError) {
    return (
      <ErrorState
        detail={error instanceof Error ? error.message : undefined}
        onRetry={() => {
          void refetch();
        }}
      />
    );
  }

  return (
    <div className="w-full space-y-3 rounded-lg border border-border bg-surface p-6 shadow-card">
      {data.completed ? (
        <>
          <h1 className="text-lg font-semibold text-text">System initialised</h1>
          <p className="text-sm text-text-muted">
            A system administrator already exists. Please sign in.
          </p>
        </>
      ) : (
        <>
          <h1 className="text-lg font-semibold text-text">System not initialised</h1>
          <p className="text-sm text-text-muted">
            The first sign-in needs a system administrator created on the server; the backend
            exposes no HTTP endpoint for it.
          </p>
          <Tooltip content="Run this in the backend repository root; the password is read from a hidden prompt.">
            <code className="block w-full rounded-md bg-surface-muted px-3 py-2 text-xs text-text">
              etla iam bootstrap admin --email you@example.com
            </code>
          </Tooltip>
        </>
      )}
    </div>
  );
}
