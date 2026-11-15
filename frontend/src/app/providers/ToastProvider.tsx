import type { ReactNode } from 'react';

import { Toaster } from '@/shared/ui';

export interface ToastProviderProps {
  children: ReactNode;
}

/**
 * Renders the toast viewport next to the application tree.
 *
 * @param props Component props.
 * @returns The wrapped children and the toaster.
 */
export function ToastProvider({ children }: ToastProviderProps) {
  return (
    <>
      {children}
      <Toaster />
    </>
  );
}
