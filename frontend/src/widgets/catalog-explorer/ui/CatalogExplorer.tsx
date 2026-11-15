import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { useQueries } from '@tanstack/react-query';
import { Columns3, Database, Folder, Plus, Search, Table2 } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router';

import { useCatalogs, type Catalog } from '@/entities/catalog';
import { useFieldSearch, useFields, type Field, type FieldSearchResult } from '@/entities/field';
import { fetchSchemas, schemaKeys, useSchemas, type Schema } from '@/entities/schema';
import { fetchTables, tableKeys, useTables, type Table } from '@/entities/table';
import {
  CreateCatalogDialog,
  DiscardCatalogConfirm,
  EditCatalogDialog,
} from '@/features/catalog-actions';
import { AddFieldDialog } from '@/features/field-actions';
import {
  CreateSchemaDialog,
  DiscardSchemaConfirm,
  EditSchemaDialog,
} from '@/features/schema-actions';
import {
  CreateTableDialog,
  DiscardTableConfirm,
  RenameTableDialog,
} from '@/features/table-actions';
import {
  catalogPath,
  columnPath,
  parseCatalogPath,
  schemaPath,
  tablePath,
  type CatalogLocation,
} from '@/shared/lib/catalog-routes';
import { useDebounced } from '@/shared/lib/use-debounced';
import { ErrorState, Skeleton, TreeMessage, TreeRow } from '@/shared/ui';

/** What the tree has to hide while a search term is active. */
interface SearchData {
  /** Whether the tree is filtered right now. */
  active: boolean;
  /** Normalised term, used to mark the matching parts of a label. */
  term: string;
  /** Ids of the catalogs that match themselves or contain a match. */
  catalogs: Set<string>;
  /** Keys of the schemas that match themselves or contain a match. */
  schemas: Set<string>;
  /** Keys of the tables that match themselves or contain a matching field. */
  tables: Set<string>;
  /** Schemas kept per catalog id. */
  schemasOf: Map<string, Schema[]>;
  /** Tables kept per `<catalog>/<schema>`. */
  tablesOf: Map<string, Table[]>;
  /** Matching fields per `<catalog>/<schema>/<table>`. */
  fieldsOf: Map<string, FieldSearchResult[]>;
  /** Whether the data behind the filter is still loading. */
  loading: boolean;
}

const EMPTY_SEARCH: SearchData = {
  active: false,
  term: '',
  catalogs: new Set<string>(),
  schemas: new Set<string>(),
  tables: new Set<string>(),
  schemasOf: new Map<string, Schema[]>(),
  tablesOf: new Map<string, Table[]>(),
  fieldsOf: new Map<string, FieldSearchResult[]>(),
  loading: false,
};

interface TreeState {
  expanded: Set<string>;
  /** Nodes the user closed while the search filter is on. */
  collapsedNodes: Set<string>;
  toggle: (key: string) => void;
  location: CatalogLocation;
  search: SearchData;
}

const TreeStateContext = createContext<TreeState | null>(null);

/**
 * Reads the state shared by the tree rows.
 *
 * @returns The tree state.
 */
function useTreeState(): TreeState {
  const state = useContext(TreeStateContext);
  if (state === null) {
    throw new Error('TreeStateContext is missing');
  }
  return state;
}

const catalogKey = (catalogId: string) => `catalog:${catalogId}`;
const schemaKey = (catalogId: string, schema: string) => `schema:${catalogId}/${schema}`;
const tableKey = (catalogId: string, schema: string, table: string) =>
  `table:${catalogId}/${schema}/${table}`;
const schemaPathKey = (catalogId: string, schema: string) => `${catalogId}/${schema}`;
const tablePathKey = (catalogId: string, schema: string, table: string) =>
  `${catalogId}/${schema}/${table}`;

/**
 * Tells whether a node shows its children.
 *
 * While a search is active the matching path is open by default, so the hits are
 * visible straight away; the user may still collapse them, and that temporary
 * state is dropped as soon as the term changes. Without a search the persistent
 * `expanded` set decides.
 *
 * @param key Key of the node.
 * @returns Whether the node is expanded.
 */
function useOpen(key: string): boolean {
  const { expanded, collapsedNodes, search } = useTreeState();
  return search.active ? !collapsedNodes.has(key) : expanded.has(key);
}

interface CatalogNodeProps {
  catalog: Catalog;
  depth: number;
}

/**
 * Renders a catalog node and, while expanded, its schemas.
 *
 * @param props Component props.
 * @returns The catalog subtree, or nothing while a search filters it out.
 */
function CatalogNode({ catalog, depth }: CatalogNodeProps) {
  const { toggle, location, search } = useTreeState();
  const navigate = useNavigate();
  const [editing, setEditing] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [creating, setCreating] = useState(false);
  const key = catalogKey(catalog.catalog_id);
  const open = useOpen(key);
  const active = location.catalogId === catalog.catalog_id && location.schema === undefined;
  const visible = !search.active || search.catalogs.has(catalog.catalog_id);

  if (!visible) {
    return null;
  }

  return (
    <>
      <TreeRow
        depth={depth}
        label={catalog.name}
        icon={<Database className="size-3.5" aria-hidden="true" />}
        to={catalogPath(catalog.catalog_id)}
        active={active}
        expanded={open}
        highlight={search.term}
        onToggle={() => {
          toggle(key);
        }}
        onCreate={() => setCreating(true)}
        createLabel="New schema"
        menuItems={[
          { label: 'Rename / edit', onSelect: () => setEditing(true) },
          { label: 'Delete catalog', danger: true, onSelect: () => setDiscarding(true) },
        ]}
      >
        {open ? <SchemaList catalogId={catalog.catalog_id} depth={depth + 1} /> : null}
      </TreeRow>

      <CreateSchemaDialog
        open={creating}
        catalogId={catalog.catalog_id}
        onClose={() => setCreating(false)}
      />
      <EditCatalogDialog open={editing} catalog={catalog} onClose={() => setEditing(false)} />
      <DiscardCatalogConfirm
        open={discarding}
        catalog={catalog}
        onClose={() => setDiscarding(false)}
        onDiscarded={() => {
          setDiscarding(false);
          if (location.catalogId === catalog.catalog_id) {
            void navigate('/catalog');
          }
        }}
      />
    </>
  );
}

interface SchemaNodeProps {
  catalogId: string;
  schema: Schema;
  depth: number;
}

/**
 * Renders a schema node and, while expanded, its tables.
 *
 * @param props Component props.
 * @returns The schema subtree, or nothing while a search filters it out.
 */
function SchemaNode({ catalogId, schema, depth }: SchemaNodeProps) {
  const { toggle, location, search } = useTreeState();
  const navigate = useNavigate();
  const [editing, setEditing] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [creating, setCreating] = useState(false);
  const key = schemaKey(catalogId, schema.name);
  const open = useOpen(key);
  const active =
    location.catalogId === catalogId &&
    location.schema === schema.name &&
    location.table === undefined;
  const visible = !search.active || search.schemas.has(key);

  if (!visible) {
    return null;
  }

  return (
    <>
      <TreeRow
        depth={depth}
        label={schema.name}
        icon={<Folder className="size-3.5" aria-hidden="true" />}
        to={schemaPath(catalogId, schema.name)}
        active={active}
        expanded={open}
        highlight={search.term}
        onToggle={() => {
          toggle(key);
        }}
        onCreate={() => setCreating(true)}
        createLabel="New table"
        menuItems={[
          { label: 'Rename / edit', onSelect: () => setEditing(true) },
          { label: 'Delete schema', danger: true, onSelect: () => setDiscarding(true) },
        ]}
      >
        {open ? (
          <TableList catalogId={catalogId} schemaName={schema.name} depth={depth + 1} />
        ) : null}
      </TreeRow>

      <CreateTableDialog
        open={creating}
        catalogId={catalogId}
        schema={schema.name}
        onClose={() => setCreating(false)}
      />
      <EditSchemaDialog
        open={editing}
        catalogId={catalogId}
        schema={schema.name}
        name={schema.name}
        description={schema.description}
        onRenamed={(newName) => {
          if (location.schema === schema.name) {
            void navigate(schemaPath(catalogId, newName), { replace: true });
          }
        }}
        onClose={() => setEditing(false)}
      />
      <DiscardSchemaConfirm
        open={discarding}
        catalogId={catalogId}
        schema={schema.name}
        onClose={() => setDiscarding(false)}
        onDiscarded={() => {
          setDiscarding(false);
          if (location.schema === schema.name) {
            void navigate(catalogPath(catalogId));
          }
        }}
      />
    </>
  );
}

interface TableNodeProps {
  catalogId: string;
  schemaName: string;
  tableName: string;
  depth: number;
}

/**
 * Renders one table leaf and, while expanded, its columns.
 *
 * @param props Component props.
 * @returns The table row, or nothing while a search filters it out.
 */
function TableNode({ catalogId, schemaName, tableName, depth }: TableNodeProps) {
  const { toggle, location, search } = useTreeState();
  const navigate = useNavigate();
  const [renaming, setRenaming] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [adding, setAdding] = useState(false);
  const key = tableKey(catalogId, schemaName, tableName);
  const open = useOpen(key);
  // The field search also returns every field of a table whose *name* matched;
  // only the fields that match themselves are worth showing below the table.
  const hitFields = (
    search.fieldsOf.get(tablePathKey(catalogId, schemaName, tableName)) ?? []
  ).filter((field) => field.field_name.toLowerCase().includes(search.term));
  // While searching, the panel only shows the fields that matched, which the
  // server already sent; the full column list is not needed.
  const fields = useFields(catalogId, schemaName, tableName, open && !search.active);
  const active =
    location.catalogId === catalogId &&
    location.schema === schemaName &&
    location.table === tableName;
  const visible = !search.active || search.tables.has(key);

  if (!visible) {
    return null;
  }

  const expandable = !search.active || hitFields.length > 0;

  return (
    <>
      <TreeRow
        depth={depth}
        label={tableName}
        icon={<Table2 className="size-3.5" aria-hidden="true" />}
        to={tablePath(catalogId, schemaName, tableName)}
        active={active}
        expanded={expandable && open}
        highlight={search.term}
        onToggle={
          expandable
            ? () => {
                toggle(key);
              }
            : undefined
        }
        onCreate={() => setAdding(true)}
        createLabel="New field"
        menuItems={[
          { label: 'Rename', onSelect: () => setRenaming(true) },
          { label: 'Delete table', danger: true, onSelect: () => setDiscarding(true) },
        ]}
      >
        {expandable && open ? (
          search.active ? (
            <FieldHitList
              catalogId={catalogId}
              schemaName={schemaName}
              tableName={tableName}
              fields={hitFields}
              depth={depth + 1}
            />
          ) : (
            <ColumnList
              catalogId={catalogId}
              schemaName={schemaName}
              tableName={tableName}
              depth={depth + 1}
              fields={fields.data ?? []}
              isPending={fields.isPending}
              isError={fields.isError}
            />
          )
        ) : null}
      </TreeRow>

      <AddFieldDialog
        open={adding}
        target={{ catalogId, schema: schemaName, table: tableName }}
        onClose={() => setAdding(false)}
      />
      <RenameTableDialog
        open={renaming}
        catalogId={catalogId}
        schema={schemaName}
        table={tableName}
        name={tableName}
        onRenamed={(newName) => {
          if (location.table === tableName) {
            void navigate(tablePath(catalogId, schemaName, newName), { replace: true });
          }
        }}
        onClose={() => setRenaming(false)}
      />
      <DiscardTableConfirm
        open={discarding}
        catalogId={catalogId}
        schema={schemaName}
        table={tableName}
        onClose={() => setDiscarding(false)}
        onDiscarded={() => {
          setDiscarding(false);
          if (location.table === tableName) {
            void navigate(schemaPath(catalogId, schemaName));
          }
        }}
      />
    </>
  );
}

interface ColumnListProps {
  catalogId: string;
  schemaName: string;
  tableName: string;
  depth: number;
  fields: Field[];
  isPending: boolean;
  isError: boolean;
}

/**
 * Renders the columns of an expanded table node.
 *
 * @param props Component props.
 * @returns The column rows.
 */
function ColumnList({
  catalogId,
  schemaName,
  tableName,
  depth,
  fields,
  isPending,
  isError,
}: ColumnListProps) {
  if (isPending) {
    return <TreeMessage depth={depth} text="Loading…" />;
  }
  if (isError) {
    return <TreeMessage depth={depth} text="Failed to load columns" />;
  }
  if (fields.length === 0) {
    return <TreeMessage depth={depth} text="No columns" />;
  }
  return (
    <>
      {fields.map((field) => (
        <ColumnNode
          key={field.name}
          catalogId={catalogId}
          schemaName={schemaName}
          tableName={tableName}
          field={field}
          depth={depth}
        />
      ))}
    </>
  );
}

interface ColumnNodeProps {
  catalogId: string;
  schemaName: string;
  tableName: string;
  field: Field;
  depth: number;
}

/**
 * Renders one column leaf pointing at its detail page.
 *
 * @param props Component props.
 * @returns The column row.
 */
function ColumnNode({ catalogId, schemaName, tableName, field, depth }: ColumnNodeProps) {
  const { location, search } = useTreeState();
  const active = location.table === tableName && location.column === field.name;

  return (
    <TreeRow
      depth={depth}
      label={field.name}
      icon={<Columns3 className="size-3.5" aria-hidden="true" />}
      to={columnPath(catalogId, schemaName, tableName, field.name)}
      active={active}
      highlight={search.term}
      trailing={<span className="font-mono text-[10px] text-text-disabled">{field.data_type}</span>}
    />
  );
}

interface FieldHitListProps {
  catalogId: string;
  schemaName: string;
  tableName: string;
  fields: FieldSearchResult[];
  depth: number;
}

/**
 * Renders the fields that matched the search term below their table.
 *
 * @param props Component props.
 * @returns The field rows.
 */
function FieldHitList({ catalogId, schemaName, tableName, fields, depth }: FieldHitListProps) {
  const { location, search } = useTreeState();

  return (
    <>
      {fields.map((field) => (
        <TreeRow
          key={field.field_name}
          depth={depth}
          label={field.field_name}
          icon={<Columns3 className="size-3.5" aria-hidden="true" />}
          to={columnPath(catalogId, schemaName, tableName, field.field_name)}
          active={location.table === tableName && location.column === field.field_name}
          highlight={search.term}
          trailing={
            <span className="font-mono text-[10px] text-text-disabled">{field.data_type}</span>
          }
        />
      ))}
    </>
  );
}

interface ChildListProps {
  catalogId: string;
  depth: number;
}

/**
 * Loads and renders the schemas of a catalog.
 *
 * While a search is active it renders the filtered subset instead, so the tree
 * keeps its shape and the siblings without a hit stay hidden.
 *
 * @param props Component props.
 * @returns The schema rows.
 */
function SchemaList({ catalogId, depth }: ChildListProps) {
  const { search } = useTreeState();
  const schemas = useSchemas(catalogId);

  if (search.active) {
    return (
      <>
        {(search.schemasOf.get(catalogId) ?? []).map((schema) => (
          <SchemaNode key={schema.schema_id} catalogId={catalogId} schema={schema} depth={depth} />
        ))}
      </>
    );
  }

  if (schemas.isPending) {
    return <TreeMessage depth={depth} text="Loading…" />;
  }
  if (schemas.isError) {
    return <TreeMessage depth={depth} text="Failed to load schemas" />;
  }
  if ((schemas.data ?? []).length === 0) {
    return <TreeMessage depth={depth} text="No schemas" />;
  }
  return (
    <>
      {(schemas.data ?? []).map((schema) => (
        <SchemaNode key={schema.schema_id} catalogId={catalogId} schema={schema} depth={depth} />
      ))}
    </>
  );
}

interface TableListProps {
  catalogId: string;
  schemaName: string;
  depth: number;
}

/**
 * Loads and renders the tables of a schema.
 *
 * While a search is active it renders the filtered subset instead.
 *
 * @param props Component props.
 * @returns The table rows.
 */
function TableList({ catalogId, schemaName, depth }: TableListProps) {
  const { search } = useTreeState();
  const tables = useTables(catalogId, schemaName);

  if (search.active) {
    return (
      <>
        {(search.tablesOf.get(schemaPathKey(catalogId, schemaName)) ?? []).map((table) => (
          <TableNode
            key={table.table_id}
            catalogId={catalogId}
            schemaName={schemaName}
            tableName={table.name}
            depth={depth}
          />
        ))}
      </>
    );
  }

  if (tables.isPending) {
    return <TreeMessage depth={depth} text="Loading…" />;
  }
  if (tables.isError) {
    return <TreeMessage depth={depth} text="Failed to load tables" />;
  }
  if ((tables.data ?? []).length === 0) {
    return <TreeMessage depth={depth} text="No tables" />;
  }
  return (
    <>
      {(tables.data ?? []).map((table) => (
        <TableNode
          key={table.table_id}
          catalogId={catalogId}
          schemaName={schemaName}
          tableName={table.name}
          depth={depth}
        />
      ))}
    </>
  );
}

/**
 * Builds the filtered tree of the current search term.
 *
 * Everything that matches survives, together with the ancestors that give it its
 * path; siblings without a hit are dropped. Catalogs, schemas and tables come
 * from the already loaded read model, matching fields from
 * `GET /catalog/search`, because loading every field of every table is not an
 * option.
 *
 * @param term Normalised search term, empty when the tree is not filtered.
 * @returns The filter state the tree rows consume.
 */
function useCatalogSearch(term: string): SearchData {
  const active = term !== '';
  const catalogs = useCatalogs();
  const catalogRows = useMemo(() => catalogs.data ?? [], [catalogs.data]);

  const schemaQueries = useQueries({
    queries: active
      ? catalogRows.map((catalog) => ({
          queryKey: schemaKeys.lists(catalog.catalog_id),
          queryFn: () => fetchSchemas(catalog.catalog_id),
        }))
      : [],
  });

  const schemaPairs = useMemo(
    () =>
      active
        ? catalogRows.flatMap((catalog, index) =>
            (schemaQueries[index]?.data ?? []).map((schema) => ({ catalog, schema })),
          )
        : [],
    [active, catalogRows, schemaQueries],
  );

  const tableQueries = useQueries({
    queries: active
      ? schemaPairs.map((pair) => ({
          queryKey: tableKeys.lists(pair.catalog.catalog_id, pair.schema.name),
          queryFn: () => fetchTables(pair.catalog.catalog_id, pair.schema.name),
        }))
      : [],
  });

  const fieldTerm = useDebounced(active ? term : '', 200);
  const fieldSearch = useFieldSearch(fieldTerm);

  return useMemo<SearchData>(() => {
    if (!active) {
      return EMPTY_SEARCH;
    }
    const matches = (name: string) => name.toLowerCase().includes(term);

    const fieldsOf = new Map<string, FieldSearchResult[]>();
    for (const hit of fieldSearch.data ?? []) {
      const key = tablePathKey(hit.catalog_id, hit.schema_name, hit.table_name);
      fieldsOf.set(key, [...(fieldsOf.get(key) ?? []), hit]);
    }

    const tablesOf = new Map<string, Table[]>();
    const tables = new Set<string>();
    schemaPairs.forEach((pair, index) => {
      const prefix = schemaPathKey(pair.catalog.catalog_id, pair.schema.name);
      const kept = (tableQueries[index]?.data ?? []).filter(
        (table) =>
          matches(table.name) ||
          fieldsOf.has(tablePathKey(pair.catalog.catalog_id, pair.schema.name, table.name)),
      );
      if (kept.length === 0) {
        return;
      }
      tablesOf.set(prefix, kept);
      for (const table of kept) {
        tables.add(tableKey(pair.catalog.catalog_id, pair.schema.name, table.name));
      }
    });

    const schemasOf = new Map<string, Schema[]>();
    const schemas = new Set<string>();
    for (const pair of schemaPairs) {
      const prefix = schemaPathKey(pair.catalog.catalog_id, pair.schema.name);
      if (!matches(pair.schema.name) && !tablesOf.has(prefix)) {
        continue;
      }
      schemasOf.set(pair.catalog.catalog_id, [
        ...(schemasOf.get(pair.catalog.catalog_id) ?? []),
        pair.schema,
      ]);
      schemas.add(schemaKey(pair.catalog.catalog_id, pair.schema.name));
    }

    const visibleCatalogs = new Set<string>();
    for (const catalog of catalogRows) {
      if (matches(catalog.name) || schemasOf.has(catalog.catalog_id)) {
        visibleCatalogs.add(catalog.catalog_id);
      }
    }

    return {
      active: true,
      term,
      catalogs: visibleCatalogs,
      schemas,
      tables,
      schemasOf,
      tablesOf,
      fieldsOf,
      loading:
        catalogs.isPending ||
        schemaQueries.some((query) => query.isPending) ||
        tableQueries.some((query) => query.isPending) ||
        // A disabled query (term shorter than two characters) stays `pending`
        // forever, so it must not keep the tree behind the skeleton.
        (fieldTerm.trim().length >= 2 && fieldSearch.isPending),
    };
  }, [
    active,
    term,
    catalogRows,
    schemaPairs,
    tableQueries,
    schemaQueries,
    fieldSearch.data,
    fieldSearch.isPending,
    fieldTerm,
    catalogs.isPending,
  ]);
}

/**
 * Renders the resource tree of the data catalog: a search box over the catalogs,
 * their schemas and their tables, expanded lazily and kept in sync with the
 * current route.
 *
 * Searching keeps the tree shape: the matching nodes stay where they are, their
 * ancestors stay visible and expanded, and everything without a hit disappears.
 *
 * @returns The catalog explorer sidebar.
 */
export function CatalogExplorer() {
  const location = useLocation();
  const parsed = useMemo(() => parseCatalogPath(location.pathname), [location.pathname]);
  const catalogs = useCatalogs();
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set<string>());
  const [createOpen, setCreateOpen] = useState(false);
  const [term, setTerm] = useState('');
  // Nodes the user closed while the search filter is active; discarded as soon
  // as the term changes so a new search opens its matches again.
  const [collapsedDuringSearch, setCollapsedDuringSearch] = useState<Set<string>>(
    () => new Set<string>(),
  );
  const navigate = useNavigate();
  const query = term.trim().toLowerCase();
  const search = useCatalogSearch(query);

  // Follow the route: the ancestors of the selected node are always open.
  useEffect(() => {
    setExpanded((current) => {
      const next = new Set(current);
      if (parsed.catalogId !== undefined) {
        next.add(catalogKey(parsed.catalogId));
      }
      if (parsed.catalogId !== undefined && parsed.schema !== undefined) {
        next.add(schemaKey(parsed.catalogId, parsed.schema));
      }
      if (
        parsed.catalogId !== undefined &&
        parsed.schema !== undefined &&
        parsed.table !== undefined
      ) {
        next.add(tableKey(parsed.catalogId, parsed.schema, parsed.table));
      }
      return next.size === current.size ? current : next;
    });
  }, [parsed.catalogId, parsed.schema, parsed.table]);

  useEffect(() => {
    setCollapsedDuringSearch(new Set<string>());
  }, [query]);

  const state = useMemo<TreeState>(
    () => ({
      expanded,
      collapsedNodes: collapsedDuringSearch,
      toggle: (key: string) => {
        if (search.active) {
          setCollapsedDuringSearch((current) => {
            const next = new Set(current);
            if (next.has(key)) {
              next.delete(key);
            } else {
              next.add(key);
            }
            return next;
          });
          return;
        }
        setExpanded((current) => {
          const next = new Set(current);
          if (next.has(key)) {
            next.delete(key);
          } else {
            next.add(key);
          }
          return next;
        });
      },
      location: parsed,
      search,
    }),
    [expanded, collapsedDuringSearch, parsed, search],
  );

  const searchState = state.search;
  const emptySearch = searchState.active && !searchState.loading && searchState.catalogs.size === 0;

  return (
    <TreeStateContext.Provider value={state}>
      <div className="flex h-full min-h-0 flex-col">
        <header className="flex h-12 shrink-0 items-center justify-between gap-2 border-b border-border-base px-3">
          <span className="text-[11px] font-semibold tracking-wider text-text-secondary uppercase">
            Resources
          </span>
          <button
            type="button"
            aria-label="New catalog"
            title="New catalog"
            onClick={() => {
              setCreateOpen(true);
            }}
            className="flex size-7 items-center justify-center rounded-sm text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
          >
            <Plus className="size-4" aria-hidden="true" />
          </button>
        </header>

        <div className="shrink-0 px-2 pt-2 pb-2">
          <div className="relative">
            <Search
              className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-text-secondary"
              aria-hidden="true"
            />
            <input
              type="search"
              aria-label="Search resources"
              placeholder="Search resources…"
              value={term}
              onChange={(event) => {
                setTerm(event.target.value);
              }}
              className="h-8 w-full rounded-md border border-border-base bg-bg-hover pr-2 pl-7 text-sm text-text-primary shadow-none outline-none transition-colors placeholder:text-text-disabled hover:border-border-strong focus:border-brand focus:bg-bg-surface focus:shadow-sm"
            />
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2" aria-label="Resource tree">
          {searchState.active ? (
            searchState.loading ? (
              <Skeleton lines={6} />
            ) : catalogs.isError ? (
              <ErrorState
                detail={catalogs.error instanceof Error ? catalogs.error.message : undefined}
                onRetry={() => {
                  void catalogs.refetch();
                }}
              />
            ) : emptySearch ? (
              <p className="px-2 py-4 text-xs text-text-secondary" role="status">
                No resource matches “{term.trim()}”.
              </p>
            ) : (
              (catalogs.data ?? []).map((catalog) => (
                <CatalogNode key={catalog.catalog_id} catalog={catalog} depth={0} />
              ))
            )
          ) : catalogs.isPending ? (
            <Skeleton lines={6} />
          ) : catalogs.isError ? (
            <ErrorState
              detail={catalogs.error instanceof Error ? catalogs.error.message : undefined}
              onRetry={() => {
                void catalogs.refetch();
              }}
            />
          ) : (catalogs.data ?? []).length === 0 ? (
            <p className="px-2 py-4 text-xs text-text-secondary">
              No catalogs yet. Use the + button to create the first one.
            </p>
          ) : (
            (catalogs.data ?? []).map((catalog) => (
              <CatalogNode key={catalog.catalog_id} catalog={catalog} depth={0} />
            ))
          )}
        </div>

        <CreateCatalogDialog
          open={createOpen}
          onClose={() => setCreateOpen(false)}
          onCreated={(catalogId) => {
            void navigate(catalogPath(catalogId));
          }}
        />
      </div>
    </TreeStateContext.Provider>
  );
}
