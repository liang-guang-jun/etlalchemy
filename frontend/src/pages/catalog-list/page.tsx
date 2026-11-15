import { useMemo, useState } from 'react';
import { Database, Plus } from 'lucide-react';
import { Link } from 'react-router';

import { useCatalogs, type Catalog } from '@/entities/catalog';
import { CreateCatalogDialog } from '@/features/catalog-actions';
import { catalogPath } from '@/shared/lib/catalog-routes';
import {
  Button,
  DataTable,
  EmptyState,
  ErrorState,
  PageHeader,
  Skeleton,
  type DataTableColumn,
} from '@/shared/ui';

/**
 * Renders the overview panel of the data catalog workspace.
 *
 * @returns The catalog overview page.
 */
export default function CatalogListPage() {
  const { data, isPending, isError, error, refetch } = useCatalogs();
  const [createOpen, setCreateOpen] = useState(false);

  const columns = useMemo<DataTableColumn<Catalog>[]>(
    () => [
      {
        key: 'name',
        header: 'Catalog',
        sortValue: (row) => row.name,
        render: (row) => (
          <Link
            to={catalogPath(row.catalog_id)}
            className="flex items-center gap-2 font-medium text-text-primary hover:underline"
          >
            <Database className="size-3.5 text-text-secondary" aria-hidden="true" />
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
    ],
    [],
  );

  return (
    <div>
      <PageHeader
        title="Data catalog"
        description="Browse metadata as catalog → schema → table → field."
        actions={
          <Button
            icon={<Plus className="size-4" />}
            onClick={() => {
              setCreateOpen(true);
            }}
          >
            New catalog
          </Button>
        }
      />

      {isPending ? (
        <Skeleton lines={5} />
      ) : isError ? (
        <ErrorState
          detail={error instanceof Error ? error.message : undefined}
          onRetry={() => {
            void refetch();
          }}
        />
      ) : (data ?? []).length === 0 ? (
        <EmptyState
          icon={<Database className="size-10" aria-hidden="true" />}
          title="No catalogs yet"
          description="Create your first catalog to register schemas, tables and fields."
          action={
            <Button
              icon={<Plus className="size-4" />}
              onClick={() => {
                setCreateOpen(true);
              }}
            >
              New catalog
            </Button>
          }
          className="py-20"
        />
      ) : (
        <DataTable rows={data ?? []} columns={columns} getRowId={(row) => row.catalog_id} />
      )}

      <CreateCatalogDialog open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}
