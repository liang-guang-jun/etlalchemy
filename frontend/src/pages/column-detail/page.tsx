import { useState } from 'react';
import { Pencil, Trash2 } from 'lucide-react';
import { Navigate, useParams } from 'react-router';

import { useCatalog } from '@/entities/catalog';
import { useFields } from '@/entities/field';
import { useSchema } from '@/entities/schema';
import { useTable } from '@/entities/table';
import { DiscardFieldConfirm, EditFieldDialog } from '@/features/field-actions';
import { LinkedTermsList } from '@/features/term-actions';
import { catalogPath, schemaPath, tablePath } from '@/shared/lib/catalog-routes';
import {
  ActionIconButton,
  ActionIconDivider,
  Badge,
  Breadcrumbs,
  ErrorState,
  ResourceDetailLayout,
  Skeleton,
} from '@/shared/ui';

type TabValue = 'terms' | 'settings';

/**
 * Renders the detail panel of one column: the terms linked to it and its
 * underlying definition.
 *
 * @returns The column detail page.
 */
export default function ColumnDetailPage() {
  const {
    catalogId = '',
    schema = '',
    table = '',
    column = '',
  } = useParams<{
    catalogId: string;
    schema: string;
    table: string;
    column: string;
  }>();
  const catalog = useCatalog(catalogId);
  const schemaRow = useSchema(catalogId, schema);
  const tableRow = useTable(catalogId, schema, table);
  const fields = useFields(catalogId, schema, table);
  const [tab, setTab] = useState<TabValue>('terms');
  const [editing, setEditing] = useState(false);
  const [discarding, setDiscarding] = useState(false);

  const schemaName = schemaRow.data?.name ?? schema;
  const tableName = tableRow.data?.name ?? table;
  const catalogName = catalog.data?.name ?? catalogId;

  if (fields.isPending) {
    return <Skeleton lines={6} />;
  }
  if (fields.isError || fields.data === undefined) {
    return (
      <ErrorState
        detail={fields.error instanceof Error ? fields.error.message : undefined}
        onRetry={() => {
          void fields.refetch();
        }}
      />
    );
  }

  const field = fields.data.find((row) => row.name === column);
  if (field === undefined) {
    // The column was renamed or deleted while open: fall back to its table.
    return <Navigate to={tablePath(catalogId, schemaName, tableName)} replace />;
  }

  const target = { catalogId, schema: schemaName, table: tableName };

  return (
    <ResourceDetailLayout
      breadcrumbs={
        <Breadcrumbs
          items={[
            { label: 'Data catalog', to: '/catalog' },
            { label: catalogName, to: catalogPath(catalogId) },
            { label: schemaName, to: schemaPath(catalogId, schemaName) },
            { label: tableName, to: tablePath(catalogId, schemaName, tableName) },
            { label: field.name },
          ]}
        />
      }
      title={field.name}
      description="Column"
      meta={
        <>
          <Badge tone="info">{field.data_type}</Badge>
          <Badge tone={field.nullable ? 'neutral' : 'success'}>
            {field.nullable ? 'Nullable' : 'Required'}
          </Badge>
          <span className="font-mono text-xs text-text-disabled">
            {schemaName}.{tableName}
          </span>
        </>
      }
      actions={
        <>
          <ActionIconButton
            label="Edit column"
            icon={<Pencil className="size-4" aria-hidden="true" />}
            onClick={() => {
              setEditing(true);
            }}
          />
          <ActionIconDivider />
          <ActionIconButton
            label="Delete column"
            tone="danger"
            icon={<Trash2 className="size-4" aria-hidden="true" />}
            onClick={() => {
              setDiscarding(true);
            }}
          />
        </>
      }
      tabs={[
        { value: 'terms', label: 'Linked terms' },
        { value: 'settings', label: 'Settings' },
      ]}
      tab={tab}
      onTabChange={(value) => {
        setTab(value === 'settings' ? 'settings' : 'terms');
      }}
    >
      {tab === 'terms' ? (
        <LinkedTermsList targetId={field.table_id} targetKind="field" fieldName={field.name} />
      ) : (
        <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <dt className="text-xs text-text-secondary">Data type</dt>
            <dd className="font-mono text-text-primary">{field.data_type}</dd>
          </div>
          <div className="flex flex-col gap-1">
            <dt className="text-xs text-text-secondary">Nullable</dt>
            <dd className="text-text-primary">{field.nullable ? 'Yes' : 'No'}</dd>
          </div>
          <div className="flex flex-col gap-1">
            <dt className="text-xs text-text-secondary">Default value</dt>
            <dd className="text-text-primary">None</dd>
          </div>
          <div className="flex flex-col gap-1">
            <dt className="text-xs text-text-secondary">Table</dt>
            <dd className="truncate font-mono text-text-primary">
              {schemaName}.{tableName}
            </dd>
          </div>
          <div className="col-span-full flex flex-col gap-1">
            <dt className="text-xs text-text-secondary">Table id</dt>
            <dd className="truncate font-mono text-[11px] text-text-disabled">{field.table_id}</dd>
          </div>
        </dl>
      )}

      <EditFieldDialog
        open={editing}
        target={target}
        field={field}
        onClose={() => {
          setEditing(false);
        }}
      />
      <DiscardFieldConfirm
        open={discarding}
        target={target}
        field={field}
        onClose={() => {
          setDiscarding(false);
        }}
      />
    </ResourceDetailLayout>
  );
}
