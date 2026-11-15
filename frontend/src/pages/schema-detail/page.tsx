import { useMemo, useState } from 'react';
import { MoreHorizontal, Pencil, Plus, Table2, Trash2 } from 'lucide-react';
import { Link, useNavigate, useParams } from 'react-router';

import { useCatalog } from '@/entities/catalog';
import { useSchema } from '@/entities/schema';
import { useTables, type Table } from '@/entities/table';
import { CommentButton } from '@/features/comment-threads';
import { DiscardSchemaConfirm, EditSchemaDialog, useChangeSchema } from '@/features/schema-actions';
import {
  CreateTableDialog,
  DiscardTableConfirm,
  RenameTableDialog,
} from '@/features/table-actions';
import { catalogPath, schemaPath, tablePath } from '@/shared/lib/catalog-routes';
import {
  ActionIconButton,
  ActionIconDivider,
  Badge,
  Breadcrumbs,
  Button,
  DataTable,
  DropdownMenu,
  ErrorState,
  ResourceDetailLayout,
  SearchInput,
  Skeleton,
  type DataTableColumn,
} from '@/shared/ui';
import { LinkedTermsList } from '@/features/term-actions';
import { MarkdownDescription } from '@/widgets/markdown-description';

type TabValue = 'tables' | 'description' | 'terms';

/**
 * Renders the detail panel of one schema with its tables.
 *
 * @returns The schema detail page.
 */
export default function SchemaDetailPage() {
  const { catalogId = '', schema = '' } = useParams<{
    catalogId: string;
    schema: string;
  }>();
  const navigate = useNavigate();
  const catalog = useCatalog(catalogId);
  const resolved = useSchema(catalogId, schema);
  const tables = useTables(catalogId, schema);

  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [renamingTable, setRenamingTable] = useState<Table | null>(null);
  const [discardingTable, setDiscardingTable] = useState<Table | null>(null);
  const [tab, setTab] = useState<TabValue>('tables');
  const [term, setTerm] = useState('');

  const schemaName = resolved.data?.name ?? schema;
  const descriptionMutation = useChangeSchema(catalogId, schemaName);

  const columns = useMemo<DataTableColumn<Table>[]>(
    () => [
      {
        key: 'name',
        header: 'Table',
        render: (row) => (
          <Link
            to={tablePath(catalogId, schemaName, row.name)}
            className="flex items-center gap-2 font-medium text-text-primary hover:underline"
          >
            <Table2 className="size-3.5 text-text-secondary" aria-hidden="true" />
            {row.name}
          </Link>
        ),
        sortValue: (row) => row.name,
      },
      {
        key: 'actions',
        header: '',
        className: 'w-12 text-right',
        render: (row) => (
          <span className="flex justify-end">
            <DropdownMenu
              iconOnly
              label={`Actions for ${row.name}`}
              icon={<MoreHorizontal className="size-3.5" aria-hidden="true" />}
              items={[
                { label: 'Rename', onSelect: () => setRenamingTable(row) },
                { label: 'Delete table', danger: true, onSelect: () => setDiscardingTable(row) },
              ]}
            />
          </span>
        ),
      },
    ],
    [catalogId, schemaName],
  );

  const rows = useMemo(() => {
    const all = tables.data ?? [];
    const query = term.trim().toLowerCase();
    return query === '' ? all : all.filter((row) => row.name.toLowerCase().includes(query));
  }, [tables.data, term]);

  if (resolved.isPending) {
    return <Skeleton lines={6} />;
  }
  if (resolved.isError || resolved.data === undefined) {
    return (
      <ErrorState
        detail={resolved.error instanceof Error ? resolved.error.message : undefined}
        onRetry={() => {
          void resolved.refetch();
        }}
      />
    );
  }

  const catalogName = catalog.data?.name ?? catalogId;

  return (
    <ResourceDetailLayout
      breadcrumbs={
        <Breadcrumbs
          items={[
            { label: 'Data catalog', to: '/catalog' },
            { label: catalogName, to: catalogPath(catalogId) },
            { label: resolved.data.name },
          ]}
        />
      }
      title={resolved.data.name}
      meta={
        <Badge tone="neutral">
          {tables.data?.length ?? 0} {tables.data?.length === 1 ? 'table' : 'tables'}
        </Badge>
      }
      actions={
        <>
          <CommentButton
            target={{
              type: 'schema',
              id: resolved.data.schema_id,
              label: resolved.data.name,
              href: schemaPath(catalogId, resolved.data.name),
            }}
          />
          <Button
            size="sm"
            icon={<Plus className="size-3.5" />}
            onClick={() => {
              setCreateOpen(true);
            }}
          >
            New table
          </Button>
          <ActionIconButton
            label="Edit schema"
            icon={<Pencil className="size-4" aria-hidden="true" />}
            onClick={() => {
              setEditing(true);
            }}
          />
          <ActionIconDivider />
          <ActionIconButton
            label="Delete schema"
            tone="danger"
            icon={<Trash2 className="size-4" aria-hidden="true" />}
            onClick={() => {
              setDiscarding(true);
            }}
          />
        </>
      }
      tabs={[
        { value: 'tables', label: 'Tables', count: tables.data?.length ?? 0 },
        { value: 'description', label: 'Description' },
        { value: 'terms', label: 'Linked terms' },
      ]}
      tab={tab}
      onTabChange={(value) => {
        setTab(value === 'terms' ? 'terms' : value === 'description' ? 'description' : 'tables');
      }}
    >
      {tab === 'tables' ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <SearchInput
              value={term}
              onChange={setTerm}
              ariaLabel="Search tables"
              placeholder="Search tables…"
            />
            <span className="text-xs text-text-disabled">
              {rows.length} of {tables.data?.length ?? 0}
            </span>
          </div>
          <DataTable
            rows={rows}
            columns={columns}
            getRowId={(row) => row.table_id}
            loading={tables.isPending}
            emptyTitle={term.trim() === '' ? 'No tables yet' : 'No matching tables'}
            emptyDescription={
              term.trim() === ''
                ? 'Create the first table of this schema.'
                : 'Try another table name.'
            }
          />
        </div>
      ) : tab === 'description' ? (
        <MarkdownDescription
          value={resolved.data.description}
          saving={descriptionMutation.isPending}
          onSave={(value) => {
            descriptionMutation.mutate({ description: value });
          }}
        />
      ) : (
        <LinkedTermsList targetId={resolved.data.schema_id} targetKind="schema" />
      )}

      <CreateTableDialog
        open={createOpen}
        catalogId={catalogId}
        schema={schemaName}
        onClose={() => setCreateOpen(false)}
      />
      <EditSchemaDialog
        open={editing}
        catalogId={catalogId}
        schema={schemaName}
        name={resolved.data.name}
        description={resolved.data.description}
        onRenamed={(newName) => {
          void navigate(schemaPath(catalogId, newName), { replace: true });
        }}
        onClose={() => setEditing(false)}
      />
      <DiscardSchemaConfirm
        open={discarding}
        catalogId={catalogId}
        schema={schemaName}
        onClose={() => setDiscarding(false)}
        onDiscarded={() => {
          void navigate(catalogPath(catalogId));
        }}
      />

      {renamingTable === null ? null : (
        <RenameTableDialog
          open
          catalogId={catalogId}
          schema={schemaName}
          table={renamingTable.name}
          name={renamingTable.name}
          onRenamed={(newName) => {
            void navigate(tablePath(catalogId, schemaName, newName), { replace: true });
          }}
          onClose={() => setRenamingTable(null)}
        />
      )}
      {discardingTable === null ? null : (
        <DiscardTableConfirm
          open
          catalogId={catalogId}
          schema={schemaName}
          table={discardingTable.name}
          onClose={() => setDiscardingTable(null)}
          onDiscarded={() => setDiscardingTable(null)}
        />
      )}
    </ResourceDetailLayout>
  );
}
