import { MotionConfig } from 'motion/react';
import type { ReactNode } from 'react';

export interface MotionProviderProps {
  children: ReactNode;
}

/**
 * Applies the shared motion defaults, honouring the reduced-motion preference.
 *
 * The spring is deliberately short: motion should read as physical feedback,
 * never as a wait.
 *
 * @param props Component props.
 * @returns The configured motion context.
 */
export function MotionProvider({ children }: MotionProviderProps) {
  return (
    <MotionConfig reducedMotion="user" transition={{ type: 'spring', stiffness: 300, damping: 30 }}>
      {children}
    </MotionConfig>
  );
}
