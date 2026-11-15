import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Merges conditional class names and resolves Tailwind conflicts.
 *
 * @param inputs Class name candidates.
 * @returns The merged class attribute.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
