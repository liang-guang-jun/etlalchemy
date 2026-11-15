import { describe, expect, it } from 'vitest';

import type { Comment } from '../api/schema';
import { buildCommentTree, indentFor, MAX_INDENT_DEPTH } from './tree';

const comment = (id: string, parent: string | null, depth = 0, body = id): Comment => ({
  comment_id: id,
  thread_id: 't',
  parent_comment_id: parent,
  author_user_id: 'u',
  author_tenant_id: null,
  body,
  mentions: [],
  created_at: '2026-01-01T00:00:00Z',
  edited_at: null,
  discarded_at: null,
  depth,
});

describe('buildCommentTree', () => {
  it('returns the roots of an empty list', () => {
    expect(buildCommentTree([])).toEqual([]);
  });

  it('keeps the creation order of the roots', () => {
    const tree = buildCommentTree([comment('a', null), comment('b', null)]);

    expect(tree.map((node) => node.comment.comment_id)).toEqual(['a', 'b']);
  });

  it('nests a reply under its parent', () => {
    const tree = buildCommentTree([comment('a', null), comment('b', 'a'), comment('c', 'b')]);

    expect(tree).toHaveLength(1);
    expect(tree[0]?.children[0]?.comment.comment_id).toBe('b');
    expect(tree[0]?.children[0]?.children[0]?.comment.comment_id).toBe('c');
  });

  it('treats a reply with an unknown parent as a root', () => {
    const tree = buildCommentTree([comment('b', 'missing')]);

    expect(tree.map((node) => node.comment.comment_id)).toEqual(['b']);
  });

  it('does not build a cycle when a reply precedes its parent', () => {
    const tree = buildCommentTree([comment('b', 'a'), comment('a', 'b')]);

    // `b` arrives first and becomes a root; `a` can then only hang below it.
    expect(tree.map((node) => node.comment.comment_id)).toEqual(['b']);
    expect(tree[0]?.children.map((node) => node.comment.comment_id)).toEqual(['a']);
    expect(tree[0]?.children[0]?.children).toEqual([]);
  });

  it('keeps the replies of one parent in creation order', () => {
    const tree = buildCommentTree([
      comment('a', null),
      comment('b', 'a'),
      comment('c', 'a'),
      comment('d', null),
      comment('e', 'a'),
    ]);

    expect(tree[0]?.children.map((node) => node.comment.comment_id)).toEqual(['b', 'c', 'e']);
    expect(tree[1]?.comment.comment_id).toBe('d');
  });
});

describe('indentFor', () => {
  it('clamps the depth to the readable maximum', () => {
    expect(indentFor(0)).toBe(0);
    expect(indentFor(2)).toBe(2);
    expect(indentFor(MAX_INDENT_DEPTH + 3)).toBe(MAX_INDENT_DEPTH);
    expect(indentFor(-1)).toBe(0);
  });
});
