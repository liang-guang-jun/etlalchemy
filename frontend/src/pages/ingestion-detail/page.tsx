import { useState } from 'react';
import { Pencil, Plug, Plus, RotateCcw, Trash2 } from 'lucide-react';
import { useNavigate, useParams } from 'react-router';

import { useConnection, useImportRuns, type Connection } from '@/entities/ingestion';
import {
  DiscardConnectionConfirm,
  EditConnectionDialog,
  RotateCredentialDialog,
  useTestConnection,
} from '@/features/connection-actions';
import { importWizardPath, ingestionPath } from '@/shared/lib/ingestion-routes';
import {
  ActionIconButton,
  ActionIconDivider,
  Badge,
  Breadcrumbs,
  Button,
  ErrorState,
  ResourceDetailLayout,
  Skeleton,
} from '@/shared/ui';
import { ImportRunTable } from '@/widgets/import-run-table';

type TabValue = 'history' | 'settings';

/**
 * Formats the stored credential without leaking it.
 *
 * @param row Connection row.
 * @returns The credential label.
 */
function credentialLabel(row: Connection): string {
  if (row.has_inline_credential) {
    return 'inline token (encrypted at rest)';
  }
  const reference = row.credential_ref ?? '';
  if (reference.startsWith('profile:')) {
    const profile = reference.slice('profile:'.length);
    return profile === '' ? 'local profile (default)' : `local profile ${profile}`;
  }
  return row.credential_ref ?? 'no credential';
}

/**
 * Renders the detail panel of one connection: its import history and its
 * configuration.
 *
 * @returns The connection detail page.
 */
export default function IngestionDetailPage() {
  const { connectionId = '' } = useParams<{ connectionId: string }>();
  const navigate = useNavigate();
  const connection = useConnection(connectionId);
  const runs = useImportRuns(connectionId, true);
  const probe = useTestConnection(connectionId);
  const [tab, setTab] = useState<TabValue>('history');
  const [editing, setEditing] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [discarding, setDiscarding] = useState(false);

  if (connection.isPending) {
    return <Skeleton lines={6} />;
  }
  if (connection.isError || connection.data === undefined) {
    return (
      <ErrorState
        detail={connection.error instanceof Error ? connection.error.message : undefined}
        onRetry={() => {
          void connection.refetch();
        }}
      />
    );
  }

  const row = connection.data;
  const history = runs.data ?? [];

  return (
    <ResourceDetailLayout
      breadcrumbs={
        <Breadcrumbs
          items={[{ label: 'Data sources', to: ingestionPath() }, { label: row.name }]}
        />
      }
      title={row.name}
      meta={
        <>
          <Badge tone="info">{row.kind}</Badge>
          <span className="font-mono text-xs text-text-secondary">{row.endpoint}</span>
        </>
      }
      actions={
        <>
          <ActionIconButton
            label="New import"
            icon={<Plus className="size-4" aria-hidden="true" />}
            onClick={() => {
              void navigate(importWizardPath(connectionId));
            }}
          />
          <ActionIconDivider />
          <ActionIconButton
            label="Edit connection"
            icon={<Pencil className="size-4" aria-hidden="true" />}
            onClick={() => {
              setEditing(true);
            }}
          />
          <ActionIconDivider />
          <ActionIconButton
            label="Delete connection"
            tone="danger"
            icon={<Trash2 className="size-4" aria-hidden="true" />}
            onClick={() => {
              setDiscarding(true);
            }}
          />
        </>
      }
      tabs={[
        { value: 'history', label: 'Import history', count: history.length },
        { value: 'settings', label: 'Settings' },
      ]}
      tab={tab}
      onTabChange={(value) => {
        setTab(value === 'settings' ? 'settings' : 'history');
      }}
    >
      {tab === 'history' ? (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs text-text-secondary">
              {runs.data === undefined ? '' : `${history.length} run(s)`}
            </span>
            {history.length === 0 ? null : (
              <Button
                size="sm"
                icon={<Plus className="size-4" />}
                onClick={() => {
                  void navigate(importWizardPath(connectionId));
                }}
              >
                Start new import
              </Button>
            )}
          </div>
          {runs.isPending ? (
            <Skeleton lines={4} />
          ) : (
            <ImportRunTable
              runs={history}
              emptyAction={
                <Button
                  icon={<Plus className="size-4" />}
                  onClick={() => {
                    void navigate(importWizardPath(connectionId));
                  }}
                >
                  Start new import
                </Button>
              }
            />
          )}
        </div>
      ) : (
        <div className="space-y-4">
          <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
            <div>
              <dt className="text-xs tracking-wide text-text-secondary uppercase">Kind</dt>
              <dd className="text-sm text-text-primary">{row.kind}</dd>
            </div>
            <div>
              <dt className="text-xs tracking-wide text-text-secondary uppercase">Endpoint</dt>
              <dd className="font-mono text-sm break-all text-text-primary">{row.endpoint}</dd>
            </div>
            <div>
              <dt className="text-xs tracking-wide text-text-secondary uppercase">
                Default catalog
              </dt>
              <dd className="text-sm text-text-primary">{row.default_catalog ?? '—'}</dd>
            </div>
            <div>
              <dt className="text-xs tracking-wide text-text-secondary uppercase">Credential</dt>
              <dd className="text-sm text-text-primary">{credentialLabel(row)}</dd>
            </div>
          </dl>

          {Object.keys(row.options).length === 0 ? null : (
            <div>
              <p className="mb-1 text-xs tracking-wide text-text-secondary uppercase">Options</p>
              <ul className="flex flex-wrap gap-1.5">
                {Object.entries(row.options).map(([key, value]) => (
                  <li
                    key={key}
                    className="rounded-sm border border-border-base bg-bg-canvas px-1.5 py-0.5 font-mono text-[11px] text-text-secondary"
                  >
                    {key}={value}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex flex-wrap gap-2 border-t border-border-base pt-3">
            <Button
              size="sm"
              variant="secondary"
              icon={<Pencil className="size-4" />}
              onClick={() => {
                setEditing(true);
              }}
            >
              Edit
            </Button>
            <Button
              size="sm"
              variant="secondary"
              icon={<RotateCcw className="size-4" />}
              onClick={() => {
                setRotating(true);
              }}
            >
              Rotate credential
            </Button>
            <Button
              size="sm"
              variant="secondary"
              icon={<Plug className="size-4" />}
              loading={probe.isPending}
              onClick={() => {
                probe.mutate();
              }}
            >
              Test connection
            </Button>
          </div>
        </div>
      )}

      <EditConnectionDialog
        open={editing}
        connection={row}
        onClose={() => {
          setEditing(false);
        }}
      />
      <RotateCredentialDialog
        open={rotating}
        connectionId={connectionId}
        kind={row.kind}
        onClose={() => {
          setRotating(false);
        }}
      />
      <DiscardConnectionConfirm
        open={discarding}
        connection={row}
        onClose={() => {
          setDiscarding(false);
        }}
        onDiscarded={() => {
          void navigate(ingestionPath());
        }}
      />
    </ResourceDetailLayout>
  );
}
