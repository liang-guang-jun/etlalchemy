import { useMemo, useState } from 'react';

import { selectIsSystemAdmin, useSessionStore } from '@/entities/session';
import { useUsers, type UserResponse } from '@/entities/user';
import { Badge, ErrorState, Input, PageContainer, PageHeader } from '@/shared/ui';
import { DataTable, type DataTableColumn } from '@/shared/ui';

/**
 * Renders the read-only user list of the IAM console.
 *
 * @returns The user list page.
 */
export default function IamUsersPage() {
  const isAdmin = useSessionStore(selectIsSystemAdmin);
  const { data, isPending, isError, error, refetch } = useUsers(isAdmin);
  const [filter, setFilter] = useState('');

  const columns = useMemo<DataTableColumn<UserResponse>[]>(
    () => [
      {
        key: 'username',
        header: 'Username',
        render: (row) => <span className="font-medium">{row.username}</span>,
        sortValue: (row) => row.username,
      },
      {
        key: 'email',
        header: 'Email',
        render: (row) => row.email,
        sortValue: (row) => row.email,
      },
      {
        key: 'display_name',
        header: 'Display name',
        render: (row) => row.display_name || '—',
        sortValue: (row) => row.display_name,
      },
      {
        key: 'status',
        header: 'Status',
        render: (row) => (
          <Badge tone={row.status === 'ACTIVE' ? 'success' : 'warning'}>{row.status}</Badge>
        ),
        sortValue: (row) => row.status,
      },
      {
        key: 'is_system_admin',
        header: 'System admin',
        render: (row) =>
          row.is_system_admin ? (
            <Badge tone="accent">Yes</Badge>
          ) : (
            <span className="text-text-muted">No</span>
          ),
        sortValue: (row) => (row.is_system_admin ? 1 : 0),
      },
    ],
    [],
  );

  const rows = useMemo(() => {
    const keyword = filter.trim().toLowerCase();
    const all = data ?? [];
    if (keyword === '') {
      return all;
    }
    return all.filter((row) =>
      `${row.username} ${row.email} ${row.display_name}`.toLowerCase().includes(keyword),
    );
  }, [data, filter]);

  return (
    <PageContainer>
      <div className="space-y-4">
        <PageHeader
          title="Users"
          description="IAM users. Management actions arrive in a later phase."
          actions={
            <Input
              placeholder="Filter by username, email or display name"
              value={filter}
              onChange={(event) => {
                setFilter(event.target.value);
              }}
              className="w-64"
            />
          }
        />
        {isError ? (
          <ErrorState
            detail={error instanceof Error ? error.message : undefined}
            onRetry={() => {
              void refetch();
            }}
          />
        ) : (
          <DataTable
            rows={rows}
            columns={columns}
            getRowId={(row) => row.user_id}
            loading={isPending}
            emptyTitle="No users"
            emptyDescription="Create the first user with etla iam admin create-user."
          />
        )}
      </div>
    </PageContainer>
  );
}
