import type { TermSearchResult, TermSummary } from '../api';

/** One term offered by the browsable tree, or one placeholder on its path. */
export interface TermTreeSource {
  /** Id of the owning domain. */
  domainId: string;
  /** Name of the owning domain, shown as the root row. */
  domainName: string;
  /** Id of the term, or `null` for a path segment that is not a term of its own. */
  termId: string | null;
  /** Full path of the term inside its domain, e.g. `Revenue/ARR`. */
  path: string;
  /** Lifecycle status, or `null` for a placeholder row. */
  status: string | null;
  /** Search hit that produced the row, when it came from a keyword search. */
  hit: TermSearchResult | null;
}

/** One rendered node of the term tree. */
export interface TermTreeNode {
  /** Stable key, independent of the term id so placeholders and terms share one. */
  key: string;
  /** Last path segment, or the domain name for a root row. */
  label: string;
  /** Path of the node inside its domain, empty for a root row. */
  path: string;
  /** Nesting level, `0` for the domain rows. */
  depth: number;
  /** Id of the owning domain. */
  domainId: string;
  /** Name of the owning domain. */
  domainName: string;
  /** Id of the term this node stands for, or `null` for a placeholder. */
  termId: string | null;
  /** Lifecycle status, or `null` for a placeholder. */
  status: string | null;
  /** Search hit backing the node, when the tree was built from a search. */
  hit: TermSearchResult | null;
  /** Children in path order. */
  children: TermTreeNode[];
}

/**
 * Builds the stable key of one node.
 *
 * The key leaves out the term id, so a placeholder created for an ancestor is
 * reused when the ancestor itself turns out to be a hit.
 *
 * @param domainId Id of the owning domain.
 * @param path Path of the node inside the domain, empty for a root row.
 * @returns The key of the node.
 */
export function termTreeKey(domainId: string, path: string): string {
  return path === '' ? `domain:${domainId}` : `term:${domainId}:${path}`;
}

/**
 * Builds the tree of the given terms, adding placeholders for the ancestors a
 * keyword search did not return.
 *
 * @param sources Terms and hits to insert.
 * @returns The domain rows, with their descendants nested below them.
 */
export function buildTermTree(sources: readonly TermTreeSource[]): TermTreeNode[] {
  const roots: TermTreeNode[] = [];
  const byDomain = new Map<string, TermTreeNode>();

  for (const source of sources) {
    let root = byDomain.get(source.domainId);
    if (root === undefined) {
      root = {
        key: termTreeKey(source.domainId, ''),
        label: source.domainName,
        path: '',
        depth: 0,
        domainId: source.domainId,
        domainName: source.domainName,
        termId: null,
        status: null,
        hit: null,
        children: [],
      };
      byDomain.set(source.domainId, root);
      roots.push(root);
    }
    if (source.path === '') {
      root.termId = source.termId;
      root.status = source.status;
      root.hit = source.hit;
      continue;
    }

    const segments = source.path.split('/');
    let parent = root;
    let accumulated = '';
    segments.forEach((segment, index) => {
      accumulated = accumulated === '' ? segment : `${accumulated}/${segment}`;
      const last = index === segments.length - 1;
      let child = parent.children.find((node) => node.label === segment);
      if (child === undefined) {
        child = {
          key: termTreeKey(source.domainId, accumulated),
          label: segment,
          path: accumulated,
          depth: parent.depth + 1,
          domainId: source.domainId,
          domainName: source.domainName,
          termId: last ? source.termId : null,
          status: last ? source.status : null,
          hit: last ? source.hit : null,
          children: [],
        };
        parent.children.push(child);
      } else if (last) {
        // The placeholder inserted for a descendant becomes the real term.
        child.termId = source.termId;
        child.status = source.status;
        child.hit = source.hit;
      }
      parent = child;
    });
  }

  const sort = (nodes: TermTreeNode[]): void => {
    nodes.sort((left, right) => left.label.localeCompare(right.label));
    for (const node of nodes) {
      sort(node.children);
    }
  };
  sort(roots);
  return roots;
}

/**
 * Converts the live terms of one domain into tree sources.
 *
 * @param domain Domain the terms belong to.
 * @param terms Terms of the domain, in path order.
 * @returns One source per term.
 */
export function summarySources(
  domain: { domain_id: string; name: string },
  terms: readonly TermSummary[],
): TermTreeSource[] {
  return terms.map((term) => ({
    domainId: domain.domain_id,
    domainName: domain.name,
    termId: term.term_id,
    path: term.path,
    status: term.status,
    hit: null,
  }));
}

/**
 * Converts keyword search hits into tree sources.
 *
 * @param hits Hits of `GET /vocabulary/search`.
 * @returns One source per hit.
 */
export function searchSources(hits: readonly TermSearchResult[]): TermTreeSource[] {
  return hits.map((hit) => ({
    domainId: hit.domain_id,
    domainName: hit.domain_name,
    termId: hit.term_id,
    path: hit.term_path,
    status: hit.status,
    hit,
  }));
}

/**
 * Walks the tree and returns the visible rows.
 *
 * @param nodes Nodes to walk, in the order they should be rendered.
 * @param collapsed Keys of the nodes whose children are hidden.
 * @returns The flat list of visible rows.
 */
export function flattenTermTree(
  nodes: readonly TermTreeNode[],
  collapsed: ReadonlySet<string>,
): TermTreeNode[] {
  const rows: TermTreeNode[] = [];
  const walk = (items: readonly TermTreeNode[]): void => {
    for (const node of items) {
      rows.push(node);
      if (!collapsed.has(node.key)) {
        walk(node.children);
      }
    }
  };
  walk(nodes);
  return rows;
}
