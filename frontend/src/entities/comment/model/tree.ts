import type { Comment } from '../api/schema';

/** One comment together with its replies. */
export interface CommentNode {
  /** The comment itself. */
  comment: Comment;
  /** Replies, in creation order. */
  children: CommentNode[];
}

/** Deepest level that still gets an extra indent; deeper replies share it. */
export const MAX_INDENT_DEPTH = 4;

/**
 * Turns the flat comment list of a thread into a reply tree.
 *
 * The API returns the comments in creation order, so a reply normally arrives
 * after its parent. A comment whose parent is missing, or that arrives before
 * it, becomes a root instead: the tree is built as the list is walked, which
 * makes a malformed parent chain impossible to turn into a cycle.
 *
 * @param comments Comments of one thread, oldest first.
 * @returns The root comments with their replies.
 */
export function buildCommentTree(comments: readonly Comment[]): CommentNode[] {
  // Registered as the list is walked, so a reply can only attach to a parent
  // that came before it; that also rules out a parent chain looping on itself.
  const nodes = new Map<string, CommentNode>();
  const roots: CommentNode[] = [];

  for (const comment of comments) {
    if (nodes.has(comment.comment_id)) {
      continue;
    }
    const node: CommentNode = { comment, children: [] };
    const parent =
      comment.parent_comment_id === null ? undefined : nodes.get(comment.parent_comment_id);
    if (parent === undefined) {
      roots.push(node);
    } else {
      parent.children.push(node);
    }
    nodes.set(comment.comment_id, node);
  }
  return roots;
}

/**
 * Clamps the indentation of a reply so deep threads stay readable.
 *
 * @param depth Parent-chain length reported by the API.
 * @returns The nesting level to render.
 */
export function indentFor(depth: number): number {
  return Math.min(Math.max(depth, 0), MAX_INDENT_DEPTH);
}
