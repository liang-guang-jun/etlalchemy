import { create } from 'zustand';

export type ToastKind = 'success' | 'error' | 'info';

/** One visible toast. */
export interface ToastItem {
  id: string;
  kind: ToastKind;
  message: string;
}

interface ToastState {
  items: ToastItem[];
  push: (kind: ToastKind, message: string) => void;
  dismiss: (id: string) => void;
}

const TOAST_TTL_MS = 5_000;

/** Store backing the imperative toast API. */
export const useToastStore = create<ToastState>((set) => ({
  items: [],
  push: (kind, message) => {
    const id = crypto.randomUUID();
    set((state) => ({ items: [...state.items, { id, kind, message }] }));
    window.setTimeout(() => {
      useToastStore.getState().dismiss(id);
    }, TOAST_TTL_MS);
  },
  dismiss: (id) => {
    set((state) => ({ items: state.items.filter((item) => item.id !== id) }));
  },
}));

/** Imperative toast API used by features and the query cache. */
export const toast = {
  success: (message: string): void => {
    useToastStore.getState().push('success', message);
  },
  error: (message: string): void => {
    useToastStore.getState().push('error', message);
  },
  info: (message: string): void => {
    useToastStore.getState().push('info', message);
  },
};
