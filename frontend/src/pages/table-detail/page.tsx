import { useState } from 'react';
import { Pencil, Trash2 } from 'lucide-react';
import { useNavigate, useParams } from 'react-router';

import { useCatalog } from '@/entities/catalog';
import { useSchema } from '@/entities/schema';
import { useTable } from '@/entities/table';
import { DiscardTableConfirm, RenameTableDialog, useChangeTable } from '@/features/table-actions';
import { catalogPath, schemaPath, tablePath } from '@/shared/lib/catalog-routes';
import { Breadcrumbs, ErrorState, Skeleton } from '@/shared/ui';
import { ActionIconButton, ActionIconDivider, Badge, ResourceDetailLayout } from '@/shared/ui';
import { CommentButton } from '@/features/comment-threads';
import { FieldTable } from '@/widgets/field-table';
import { LinkedTermsList } from '@/features/term-actions';
import { MarkdownDescription } from '@/widgets/markdown-description';

type TabValue = 'fields' | 'description' | 'terms';

/**
 * Renders the detail panel of one table: its fields, its description and the
 * terms linked to the table itself.
 *
 * @returns The table detail page.
 */
export default function TableDetailPage() {
  const {
    catalogId = '',
    schema = '',
    table = '',
  } = useParams<{
    catalogId: string;
    schema: string;
    table: string;
  }>();
  const navigate = useNavigate();
  const catalog = useCatalog(catalogId);
  const schemaRow = useSchema(catalogId, schema);
  const resolved = useTable(catalogId, schema, table);
  const schemaName = schemaRow.data?.name ?? schema;
  const tableName = resolved.data?.name ?? table;
  const descriptionMutation = useChangeTable(catalogId, schemaName, tableName);
  const [tab, setTab] = useState<TabValue>('fields');
  const [renaming, setRenaming] = useState(false);
  const [discarding, setDiscarding] = useState(false);

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
            { label: schemaName, to: schemaPath(catalogId, schemaName) },
            { label: resolved.data.name },
          ]}
        />
      }
      title={resolved.data.name}
      meta={<Badge tone="neutral">{schemaName}</Badge>}
      actions={
        <>
          <CommentButton
            target={{
              type: 'table',
              id: resolved.data.table_id,
              label: resolved.data.name,
              href: tablePath(catalogId, schemaName, resolved.data.name),
            }}
          />
          <ActionIconDivider />
          <ActionIconButton
            label="Rename table"
            icon={<Pencil className="size-4" aria-hidden="true" />}
            onClick={() => {
              setRenaming(true);
            }}
          />
          <ActionIconDivider />
          <ActionIconButton
            label="Delete table"
            tone="danger"
            icon={<Trash2 className="size-4" aria-hidden="true" />}
            onClick={() => {
              setDiscarding(true);
            }}
          />
        </>
      }
      tabs={[
        { value: 'fields', label: 'Fields' },
        { value: 'description', label: 'Description' },
        { value: 'terms', label: 'Linked terms' },
      ]}
      tab={tab}
      onTabChange={(value) => {
        setTab(value as TabValue);
      }}
    >
      {tab === 'fields' ? (
        <FieldTable catalogId={catalogId} schema={schemaName} table={resolved.data.name} />
      ) : tab === 'description' ? (
        <MarkdownDescription
          value={resolved.data.description}
          saving={descriptionMutation.isPending}
          onSave={(value) => {
            descriptionMutation.mutate({ description: value });
          }}
        />
      ) : (
        <LinkedTermsList targetId={resolved.data.table_id} targetKind="table" />
      )}

      <RenameTableDialog
        open={renaming}
        catalogId={catalogId}
        schema={schemaName}
        table={resolved.data.name}
        name={resolved.data.name}
        onRenamed={(newName) => {
          void navigate(
            `${schemaPath(catalogId, schemaName)}/tables/${encodeURIComponent(newName)}`,
            {
              replace: true,
            },
          );
        }}
        onClose={() => setRenaming(false)}
      />
      <DiscardTableConfirm
        open={discarding}
        catalogId={catalogId}
        schema={schemaName}
        table={resolved.data.name}
        onClose={() => setDiscarding(false)}
        onDiscarded={() => {
          void navigate(schemaPath(catalogId, schemaName));
        }}
      />
    </ResourceDetailLayout>
  );
}
