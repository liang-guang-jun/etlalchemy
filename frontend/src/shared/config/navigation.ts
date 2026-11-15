import {
  BookOpen,
  Building2,
  Database,
  Earth,
  KeyRound,
  Network,
  ScrollText,
  Shield,
  Sparkles,
  Users,
  type LucideIcon,
} from 'lucide-react';

/** One entry of the application navigation. */
export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}

/**
 * Icon rail entries: only the core modelling and ingestion flow. Discussions
 * live in the header and the IAM console is folded into the settings menu.
 */
export const NAV_ITEMS: NavItem[] = [
  { to: '/agent', label: 'Agent', icon: Sparkles },
  { to: '/catalog', label: 'Data catalog', icon: Database },
  { to: '/semantic', label: 'Semantic models', icon: Network },
  { to: '/vocabulary', label: 'Business terms', icon: BookOpen },
  { to: '/ingestion', label: 'Data sources', icon: Earth },
];

/**
 * IAM console entries owned by the system administrator, rendered inside the
 * header settings menu instead of the sidebar.
 */
export const ADMIN_NAV_ITEMS: NavItem[] = [
  { to: '/iam/users', label: 'Users', icon: Users },
  { to: '/iam/tenants', label: 'Tenants', icon: Building2 },
  { to: '/iam/groups', label: 'Groups & permissions', icon: Shield },
  { to: '/iam/providers', label: 'Providers', icon: KeyRound },
  { to: '/iam/audit', label: 'Audit log', icon: ScrollText },
];

/**
 * Names the section a path belongs to.
 *
 * The agent shows it as the context chip above its input, so a prompt typed on
 * a table page says which part of the product it came from.
 *
 * @param pathname Path of the current location.
 * @returns The matching navigation label, or `null` for an unknown path.
 */
export function describeLocation(pathname: string): string | null {
  const match = [...NAV_ITEMS, ...ADMIN_NAV_ITEMS].find(
    (item) => pathname === item.to || pathname.startsWith(`${item.to}/`),
  );
  return match?.label ?? null;
}

/** One object of the chain between a section and the current page. */
export interface LocationResource {
  /** Kind of the object, e.g. `table`. */
  kind: string;
  /** Name, id or slug from the path; empty for a page with no object. */
  name: string;
}

/** Placement of the current page inside the product. */
export interface LocationContext {
  /** Navigation section, or `null` for a path outside the navigation. */
  section: string | null;
  /** Objects below the section, outermost first. */
  resources: LocationResource[];
  /** Pathname plus search, as the address bar shows it. */
  path: string;
}

/** Keyword of a path segment and the object kind it introduces. */
const SEGMENT_KINDS: Record<string, string> = {
  schemas: 'schema',
  tables: 'table',
  columns: 'column',
  terms: 'term',
  'new-import': 'import wizard',
};

/** Root object a section lists, used for the first id of a page. */
const SECTION_ROOTS: Record<string, string> = {
  '/catalog': 'catalog',
  '/semantic': 'semantic model',
  '/vocabulary': 'domain',
  '/ingestion': 'data source',
  '/iam/users': 'user',
  '/iam/tenants': 'tenant',
  '/iam/groups': 'group',
  '/iam/providers': 'provider',
};

/**
 * Resolves the objects a path points at, section first.
 *
 * The floating widget hands the result to the agent with every prompt, so a
 * question such as "which of these can I delete?" carries the catalog, schema
 * and table the reader is looking at instead of forcing a clarifying turn.
 *
 * @param pathname Path of the current location.
 * @param search Query string of the current location, leading `?` included.
 * @returns The section, the object chain and the full path.
 */
export function describeLocationContext(pathname: string, search = ''): LocationContext {
  const match = [...NAV_ITEMS, ...ADMIN_NAV_ITEMS].find(
    (item) => pathname === item.to || pathname.startsWith(`${item.to}/`),
  );
  const path = `${pathname}${search}`;
  if (match === undefined) {
    return { section: null, resources: [], path };
  }
  const rest = pathname
    .slice(match.to.length)
    .split('/')
    .filter((segment) => segment !== '');
  const resources: LocationResource[] = [];
  const root = SECTION_ROOTS[match.to];
  const rootName = rest[0];
  if (root !== undefined && rootName !== undefined) {
    resources.push({ kind: root, name: rootName });
  }
  // Everything after the first id is a `/<keyword>/<value>` pair, exactly like
  // the route table spells it (`/catalog/:id/schemas/:schema/tables/:table`).
  for (let index = 1; index < rest.length; index += 2) {
    const keyword = rest[index] ?? '';
    const value = rest[index + 1] ?? '';
    resources.push({ kind: SEGMENT_KINDS[keyword] ?? keyword, name: value });
  }
  return { section: match.label, resources, path };
}

/**
 * Renders a location as one line, e.g. `Data catalog › catalog crm › table contacts`.
 *
 * @param context Placement resolved by {@link describeLocationContext}.
 * @returns The summary, or `null` when the path names nothing.
 */
export function formatLocationContext(context: LocationContext): string | null {
  const parts = [
    ...(context.section === null ? [] : [context.section]),
    ...context.resources.map((item) =>
      item.name === '' ? item.kind : `${item.kind} ${item.name}`,
    ),
  ];
  return parts.length === 0 ? null : parts.join(' › ');
}

/**
 * Builds the page context the chat panel sends with a prompt.
 *
 * The backend splices it into the system prompt, so the text itself stays out of
 * the stored message: it names the page and the path the agent can open.
 *
 * @param context Placement resolved by {@link describeLocationContext}.
 * @returns The two-line summary, or `null` when the path names nothing.
 */
export function locationContextNote(context: LocationContext): string | null {
  const summary = formatLocationContext(context);
  if (summary === null) {
    return null;
  }
  return `${summary}\nPath: ${context.path}`;
}
