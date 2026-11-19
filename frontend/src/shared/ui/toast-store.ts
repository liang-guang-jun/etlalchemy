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
    // One failing lookup can report the same message once per affected row, so a
    // visible toast absorbs the repeats instead of stacking a wall of them. The
    // TTL of the first one still decides when the message goes away.
    const created: ToastItem[] = [];
    set((state) => {
      if (state.items.some((item) => item.kind === kind && item.message === message)) {
        return state;
      }
      const item: ToastItem = { id: crypto.randomUUID(), kind, message };
      created.push(item);
      return { items: [...state.items, item] };
    });
    const added = created[0];
    if (added === undefined) {
      return;
    }
    window.setTimeout(() => {
      useToastStore.getState().dismiss(added.id);
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
