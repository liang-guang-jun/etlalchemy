import { Link } from 'react-router';

import { TARGET_NOUNS, targetHref, useTarget } from '@/entities/comment';
import { CommentPanelBody, useCommentPanelStore } from '@/features/comment-threads';
import { Drawer } from '@/shared/ui';

/**
 * Renders the discussion panel of the target that was last opened.
 *
 * The drawer is mounted once by `AppShell`, so any button, tree row or canvas
 * inspector can open a discussion by calling `openComments`.
 *
 * @returns The discussion drawer.
 */
export function CommentPanelDrawer() {
  const target = useCommentPanelStore((state) => state.target);
  const closePanel = useCommentPanelStore((state) => state.closePanel);
  const unknown = target !== null && target.href === undefined;
  const described = useTarget(
    unknown ? (target?.type ?? '') : '',
    unknown ? (target?.id ?? '') : '',
  );
  const href =
    target?.href ?? (described.data === undefined ? undefined : targetHref(described.data));
  const label = described.data !== undefined ? described.data.name : (target?.label ?? '');

  return (
    <Drawer
      open={target !== null}
      title={
        target === null ? (
          'Discussion'
        ) : (
          <span className="flex min-w-0 items-baseline gap-2">
            <span className="shrink-0 text-text-secondary">{TARGET_NOUNS[target.type]}</span>
            {href === undefined ? (
              <span className="truncate">{label}</span>
            ) : (
              <Link
                to={href}
                title={`Open ${label}`}
                className="truncate transition-colors hover:text-text-primary hover:underline"
              >
                {label}
              </Link>
            )}
          </span>
        )
      }
      width="lg"
      onClose={closePanel}
    >
      {target === null ? null : <CommentPanelBody target={target} />}
    </Drawer>
  );
}
