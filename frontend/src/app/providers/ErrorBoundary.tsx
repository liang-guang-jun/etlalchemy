import { Component, type ErrorInfo, type ReactNode } from 'react';

import { Button } from '@/shared/ui';

export interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Catches rendering errors of the whole application.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('render failed', error, info.componentStack);
  }

  override render(): ReactNode {
    const { error } = this.state;
    if (error === null) {
      return this.props.children;
    }
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 p-6 text-center">
        <h1 className="text-lg font-semibold text-text">Rendering failed</h1>
        <p className="max-w-md text-sm text-text-muted">{error.message}</p>
        <Button
          onClick={() => {
            window.location.assign('/');
          }}
        >
          Back to home
        </Button>
      </div>
    );
  }
}
