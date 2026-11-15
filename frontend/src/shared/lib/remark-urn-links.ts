import { parseUrn, URN_PATTERN, type UrnTarget } from './urn';

/** Subset of the mdast nodes this plugin rewrites. */
interface MdastNode {
  type: string;
  value?: string;
  url?: string;
  title?: string | null;
  children?: MdastNode[];
}

/** Nodes that must never be rewritten. */
const OPAQUE = new Set(['code', 'html', 'link', 'linkReference', 'image']);

/**
 * Builds the link node of one resolved URN.
 *
 * The URN travels in the title, so a renderer can replace the short label with
 * the name the read model knows.
 *
 * @param target Resolved URN.
 * @returns The mdast link node.
 */
function linkNode(target: UrnTarget): MdastNode {
  return {
    type: 'link',
    url: target.href,
    title: target.urn,
    children: [{ type: 'text', value: target.label }],
  };
}

/**
 * Splits one text node into text and link nodes.
 *
 * @param value Text of the node.
 * @returns The replacement nodes, or `null` when the text holds no URN.
 */
function split(value: string): MdastNode[] | null {
  URN_PATTERN.lastIndex = 0;
  const nodes: MdastNode[] = [];
  let last = 0;
  let match = URN_PATTERN.exec(value);
  while (match !== null) {
    const target = parseUrn(match[0]);
    if (target === null) {
      match = URN_PATTERN.exec(value);
      continue;
    }
    if (match.index > last) {
      nodes.push({ type: 'text', value: value.slice(last, match.index) });
    }
    nodes.push(linkNode(target));
    // The match may carry the punctuation of the sentence; it stays as text.
    last = match.index + target.urn.length;
    match = URN_PATTERN.exec(value);
  }
  if (nodes.length === 0) {
    return null;
  }
  if (last < value.length) {
    nodes.push({ type: 'text', value: value.slice(last) });
  }
  return nodes;
}

/**
 * Walks the tree and rewrites every URN it finds in text or inline code.
 *
 * @param node Node to visit.
 */
function walk(node: MdastNode): void {
  if (node.children === undefined) {
    return;
  }
  node.children = node.children.flatMap((child) => {
    if (OPAQUE.has(child.type)) {
      return [child];
    }
    if (child.type === 'inlineCode' && child.value !== undefined) {
      // A model that writes a URN as code still means the object, so the
      // backticks become a link; any other code stays code.
      const target = parseUrn(child.value);
      return target === null ? [child] : [linkNode(target)];
    }
    if (child.type === 'text' && child.value !== undefined) {
      return split(child.value) ?? [child];
    }
    walk(child);
    return [child];
  });
}

/**
 * Turns object URNs in markdown text into links to their page.
 *
 * A plugin is used instead of a text replacement so fenced code blocks and
 * existing links are never rewritten. Inline code is the exception: a model
 * writes an id in backticks, so a URN that fills the whole span still becomes a
 * link while any other span stays code.
 *
 * @returns The mdast transformer.
 */
export function remarkUrnLinks() {
  return (tree: MdastNode): void => {
    walk(tree);
  };
}
