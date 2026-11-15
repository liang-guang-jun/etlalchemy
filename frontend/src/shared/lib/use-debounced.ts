import { useEffect, useState } from 'react';

/**
 * Delays a fast-changing value, so a search only queries after typing stops.
 *
 * @param value Value to delay.
 * @param delay Delay in milliseconds.
 * @returns The value after it stopped changing for `delay` milliseconds.
 */
export function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(value);
    }, delay);
    return () => {
      window.clearTimeout(timer);
    };
  }, [value, delay]);

  return debounced;
}
