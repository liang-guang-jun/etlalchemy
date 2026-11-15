import { useMemo, useState } from 'react';
import { Folder, MoreHorizontal, Pencil, Plus, Trash2 } from 'lucide-react';
import { Link, useNavigate, useParams } from 'react-router';

import { useCatalog } from '@/entities/catalog';
import { useSchemas, type Schema } from '@/entities/schema';
import { CommentButton } from '@/features/comment-threads';
import {
  DiscardCatalogConfirm,
  EditCatalogDialog,
  useChangeCatalog,
} from '@/features/catalog-actions';
import {
  CreateSchemaDialog,
  DiscardSchemaConfirm,
  EditSchemaDialog,
} from '@/features/schema-actions';
import { schemaPath } from '@/shared/lib/catalog-routes';
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

type TabValue = 'schemas' | 'description' | 'terms';

interface SchemaRowActionsProps {
  catalogId: string;
  schema: Schema;
}

/**
 * Renders the row menu of one schema with its edit and delete dialogs.
 *
 * @param props Component props.
 * @returns The action menu.
 */
function SchemaRowActions({ catalogId, schema }: SchemaRowActionsProps) {
  const [editing, setEditing] = useState(false);
  const [discarding, setDiscarding] = useState(false);

  return (
    <>
      <DropdownMenu
        iconOnly
        label={`Actions for ${schema.name}`}
        icon={<MoreHorizontal className="size-3.5" aria-hidden="true" />}
        items={[
          { label: 'Rename / edit', onSelect: () => setEditing(true) },
          { label: 'Delete schema', danger: true, onSelect: () => setDiscarding(true) },
        ]}
      />
      <EditSchemaDialog
        open={editing}
        catalogId={catalogId}
        schema={schema.name}
        name={schema.name}
        description={schema.description}
        onClose={() => setEditing(false)}
      />
      <DiscardSchemaConfirm
        open={discarding}
        catalogId={catalogId}
        schema={schema.name}
        onClose={() => setDiscarding(false)}
        onDiscarded={() => setDiscarding(false)}
      />
    </>
  );
}

/**
 * Renders the detail panel of one catalog.
 *
 * @returns The catalog detail page.
 */
export default function CatalogDetailPage() {
  const { catalogId = '' } = useParams<{ catalogId: string }>();
  const navigate = useNavigate();
  const catalog = useCatalog(catalogId);
  const schemas = useSchemas(catalogId);
  const descriptionMutation = useChangeCatalog(catalogId);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [tab, setTab] = useState<TabValue>('schemas');
  const [term, setTerm] = useState('');

  const columns = useMemo<DataTableColumn<Schema>[]>(
    () => [
      {
        key: 'name',
        header: 'Schema',
        sortValue: (row) => row.name,
        render: (row) => (
          <Link
            to={schemaPath(catalogId, row.name)}
            className="flex items-center gap-2 font-medium text-text-primary hover:underline"
          >
            <Folder className="size-3.5 text-text-secondary" aria-hidden="true" />
            {row.name}
          </Link>
        ),
      },
      {
        key: 'description',
        header: 'Description',
        sortValue: (row) => row.description,
        render: (row) => (
          <span className="line-clamp-1 text-text-secondary">{row.description || '—'}</span>
        ),
      },
      {
        key: 'actions',
        header: '',
        className: 'w-12 text-right',
        render: (row) => (
          <span className="flex justify-end">
            <SchemaRowActions catalogId={catalogId} schema={row} />
          </span>
        ),
      },
    ],
    [catalogId],
  );

  const rows = useMemo(() => {
    const all = schemas.data ?? [];
    const query = term.trim().toLowerCase();
    if (query === '') {
      return all;
    }
    return all.filter(
      (row) =>
        row.name.toLowerCase().includes(query) || row.description.toLowerCase().includes(query),
    );
  }, [schemas.data, term]);

  if (catalog.isPending) {
    return <Skeleton lines={6} />;
  }
  if (catalog.isError || catalog.data === undefined) {
    return (
      <ErrorState
        detail={catalog.error instanceof Error ? catalog.error.message : undefined}
        onRetry={() => {
          void catalog.refetch();
        }}
      />
    );
  }

  return (
    <ResourceDetailLayout
      breadcrumbs={
        <Breadcrumbs
          items={[{ label: 'Data catalog', to: '/catalog' }, { label: catalog.data.name }]}
        />
      }
      title={catalog.data.name}
      meta={
        <Badge tone="neutral">
          {schemas.data?.length ?? 0} {schemas.data?.length === 1 ? 'schema' : 'schemas'}
        </Badge>
      }
      actions={
        <>
          <Button
            size="sm"
            icon={<Plus className="size-3.5" />}
            onClick={() => {
              setCreateOpen(true);
            }}
          >
            New schema
          </Button>
          <CommentButton
            target={{
              type: 'catalog',
              id: catalog.data.catalog_id,
              label: catalog.data.name,
              href: `/catalog/${catalog.data.catalog_id}`,
            }}
          />
          <ActionIconButton
            label="Edit catalog"
            icon={<Pencil className="size-4" aria-hidden="true" />}
            onClick={() => {
              setEditing(true);
            }}
          />
          <ActionIconDivider />
          <ActionIconButton
            label="Delete catalog"
            tone="danger"
            icon={<Trash2 className="size-4" aria-hidden="true" />}
            onClick={() => {
              setDiscarding(true);
            }}
          />
        </>
      }
      tabs={[
        { value: 'schemas', label: 'Schemas', count: schemas.data?.length ?? 0 },
        { value: 'description', label: 'Description' },
        { value: 'terms', label: 'Linked terms' },
      ]}
      tab={tab}
      onTabChange={(value) => {
        setTab(value === 'terms' ? 'terms' : value === 'description' ? 'description' : 'schemas');
      }}
    >
      {tab === 'schemas' ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <SearchInput
              value={term}
              onChange={setTerm}
              ariaLabel="Search schemas"
              placeholder="Search schemas…"
            />
            <span className="text-xs text-text-disabled">
              {rows.length} of {schemas.data?.length ?? 0}
            </span>
          </div>
          <DataTable
            rows={rows}
            columns={columns}
            getRowId={(row) => row.schema_id}
            loading={schemas.isPending}
            emptyTitle={term.trim() === '' ? 'No schemas yet' : 'No matching schemas'}
            emptyDescription={
              term.trim() === ''
                ? 'Create the first schema to organise tables.'
                : 'Try another name or description.'
            }
          />
        </div>
      ) : tab === 'description' ? (
        <MarkdownDescription
          value={catalog.data.description}
          saving={descriptionMutation.isPending}
          onSave={(value) => {
            descriptionMutation.mutate({ description: value });
          }}
        />
      ) : (
        <LinkedTermsList targetId={catalogId} targetKind="catalog" />
      )}

      <CreateSchemaDialog
        open={createOpen}
        catalogId={catalogId}
        onClose={() => setCreateOpen(false)}
      />
      <EditCatalogDialog open={editing} catalog={catalog.data} onClose={() => setEditing(false)} />
      <DiscardCatalogConfirm
        open={discarding}
        catalog={catalog.data}
        onClose={() => setDiscarding(false)}
        onDiscarded={() => {
          void navigate('/catalog');
        }}
      />
    </ResourceDetailLayout>
  );
}
