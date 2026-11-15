import { create } from 'zustand';

import type { CommentTarget } from '@/entities/comment';

interface CommentPanelState {
  /** Target whose threads the panel shows, or `null` while it is closed. */
  target: CommentTarget | null;
  /** Thread the panel opens expanded, or `null` for the plain list. */
  focusThreadId: string | null;
  /** Whether the global inbox drawer is showing. */
  inboxOpen: boolean;
  /** Opens the panel for one target, optionally with a thread expanded. */
  openPanel: (target: CommentTarget, threadId?: string) => void;
  /** Closes the panel. */
  closePanel: () => void;
  /** Opens the global inbox drawer. */
  openInbox: () => void;
  /** Closes the global inbox drawer. */
  closeInbox: () => void;
}

/**
 * Panel state shared by every entry point.
 *
 * The drawers live once in `AppShell`; a header button, a tree row or the
 * canvas inspector only has to call `openPanel` with the target it describes.
 */
export const useCommentPanelStore = create<CommentPanelState>()((set) => ({
  target: null,
  focusThreadId: null,
  inboxOpen: false,
  openPanel: (target, threadId) => {
    set({ target, focusThreadId: threadId ?? null });
  },
  closePanel: () => {
    set({ target: null, focusThreadId: null });
  },
  openInbox: () => {
    set({ inboxOpen: true });
  },
  closeInbox: () => {
    set({ inboxOpen: false });
  },
}));

/**
 * Opens the panel of one target from anywhere, without subscribing to the store.
 *
 * @param target Target to discuss.
 * @param threadId Thread to expand, or `undefined` for the list.
 */
export function openComments(target: CommentTarget, threadId?: string): void {
  useCommentPanelStore.getState().openPanel(target, threadId);
}
