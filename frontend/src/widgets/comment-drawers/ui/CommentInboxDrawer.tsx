import { CommentInbox, useCommentPanelStore } from '@/features/comment-threads';
import { Drawer } from '@/shared/ui';

/**
 * Renders the global discussion inbox.
 *
 * Picking a thread closes the inbox and opens its contextual panel, which is
 * where the replies are written.
 *
 * @returns The inbox drawer.
 */
export function CommentInboxDrawer() {
  const inboxOpen = useCommentPanelStore((state) => state.inboxOpen);
  const closeInbox = useCommentPanelStore((state) => state.closeInbox);

  return (
    <Drawer open={inboxOpen} title="Discussions" onClose={closeInbox}>
      <CommentInbox onOpened={closeInbox} />
    </Drawer>
  );
}
