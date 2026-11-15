import { useMemo, useState } from 'react';
import { Pencil, Plus, Trash2 } from 'lucide-react';
import { Link, useNavigate, useParams } from 'react-router';

import { useDomain } from '@/entities/domain';
import { useTerms, type TermSummary } from '@/entities/term';
import { DiscardDomainConfirm, DomainDialog } from '@/features/domain-actions';
import { CreateTermDialog, TermActionsMenu } from '@/features/term-actions';
import { cn } from '@/shared/lib/cn';
import { markdownToText } from '@/shared/lib/markdown';
import { termPath } from '@/shared/lib/vocabulary-routes';
import {
  Badge,
  Breadcrumbs,
  Button,
  ColorDot,
  DataTable,
  ErrorState,
  PageHeader,
  Skeleton,
  type BadgeTone,
  type DataTableColumn,
} from '@/shared/ui';

type StatusFilter = 'all' | 'draft' | 'approved' | 'deprecated';

const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'draft', label: 'Draft' },
  { value: 'approved', label: 'Approved' },
  { value: 'deprecated', label: 'Deprecated' },
];

/** Background and text tone of each status filter badge. */
const FILTER_TONES: Record<StatusFilter, string> = {
  all: 'bg-bg-canvas text-text-secondary',
  draft: 'bg-bg-hover text-text-secondary',
  approved: 'bg-success/10 text-success',
  deprecated: 'bg-danger/10 text-danger',
};

/**
 * Maps a term status to its badge tone.
 *
 * @param status Lifecycle status.
 * @returns The badge tone.
 */
function statusTone(status: string): BadgeTone {
  if (status === 'approved') {
    return 'success';
  }
  if (status === 'deprecated') {
    return 'danger';
  }
  return 'neutral';
}

/**
 * Renders the detail panel of one domain with its terms.
 *
 * @returns The domain detail page.
 */
export default function VocabularyDomainPage() {
  const { domainId = '' } = useParams<{ domainId: string }>();
  const navigate = useNavigate();
  const domain = useDomain(domainId);
  const terms = useTerms(domainId);
  const [filter, setFilter] = useState<StatusFilter>('all');
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [discarding, setDiscarding] = useState(false);

  const counts = useMemo(() => {
    const all = terms.data ?? [];
    return {
      all: all.length,
      draft: all.filter((term) => term.status === 'draft').length,
      approved: all.filter((term) => term.status === 'approved').length,
      deprecated: all.filter((term) => term.status === 'deprecated').length,
    };
  }, [terms.data]);

  const rows = useMemo(() => {
    const all = terms.data ?? [];
    return filter === 'all' ? all : all.filter((term) => term.status === filter);
  }, [terms.data, filter]);

  const columns = useMemo<DataTableColumn<TermSummary>[]>(
    () => [
      {
        key: 'path',
        header: 'Term',
        render: (row) => (
          <span className="flex flex-col gap-0.5">
            <Link
              to={termPath(domainId, row.term_id)}
              className="flex items-center gap-2 font-medium text-text-primary hover:underline"
            >
              <ColorDot color={row.color} />
              {row.name}
            </Link>
            {row.path === row.name ? null : (
              <span className="pl-5 text-xs text-text-disabled">{row.path}</span>
            )}
          </span>
        ),
        sortValue: (row) => row.path,
      },
      {
        key: 'definition',
        header: 'Definition',
        render: (row) => (
          <span className="line-clamp-2 text-sm text-text-secondary">
            {markdownToText(row.definition)}
          </span>
        ),
      },
      {
        key: 'status',
        header: 'Status',
        className: 'w-32',
        render: (row) => <Badge tone={statusTone(row.status)}>{row.status}</Badge>,
        sortValue: (row) => row.status,
      },
      {
        key: 'actions',
        header: '',
        className: 'w-10 text-right',
        render: (row) => (
          <span className="flex justify-end">
            <TermActionsMenu
              domainId={domainId}
              termId={row.term_id}
              name={row.name}
              status={row.status}
            />
          </span>
        ),
      },
    ],
    [domainId],
  );

  if (domain.isPending) {
    return <Skeleton lines={6} />;
  }
  if (domain.isError || domain.data === undefined) {
    return (
      <ErrorState
        detail={domain.error instanceof Error ? domain.error.message : undefined}
        onRetry={() => {
          void domain.refetch();
        }}
      />
    );
  }

  return (
    <div>
      <PageHeader
        title={domain.data.name}
        description={domain.data.description || 'No description'}
        breadcrumb={
          <span className="flex items-center gap-2">
            <Breadcrumbs
              items={[{ label: 'Business terms', to: '/vocabulary' }, { label: domain.data.name }]}
            />
            <Badge tone="neutral">Domain</Badge>
          </span>
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
              New term
            </Button>
            <Button
              size="sm"
              variant="secondary"
              icon={<Pencil className="size-3.5" />}
              onClick={() => {
                setEditing(true);
              }}
            >
              Edit
            </Button>
            <Button
              size="sm"
              variant="danger-ghost"
              icon={<Trash2 className="size-3.5" />}
              onClick={() => {
                setDiscarding(true);
              }}
            >
              Delete
            </Button>
          </>
        }
      />

      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        {STATUS_FILTERS.map((option) => (
          <button
            key={option.value}
            type="button"
            aria-pressed={filter === option.value}
            onClick={() => {
              setFilter(option.value);
            }}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide transition-all',
              FILTER_TONES[option.value],
              filter === option.value
                ? 'border-current shadow-sm'
                : 'border-border-base opacity-70 hover:opacity-100',
            )}
          >
            {option.label}
            <span className="rounded-sm px-1 text-[10px] tabular-nums opacity-80">
              {counts[option.value]}
            </span>
          </button>
        ))}
      </div>

      <DataTable
        rows={rows}
        columns={columns}
        getRowId={(row) => row.term_id}
        loading={terms.isPending}
        emptyTitle={filter === 'all' ? 'No terms yet' : `No ${filter} terms`}
        emptyDescription={
          filter === 'all'
            ? 'Create the first term of this domain.'
            : 'Switch the filter to see the other terms.'
        }
        emptyAction={
          filter === 'all' ? (
            <Button
              size="sm"
              variant="ghost"
              icon={<Plus className="size-3.5" />}
              onClick={() => {
                setCreateOpen(true);
              }}
            >
              Create the first term
            </Button>
          ) : undefined
        }
      />

      <CreateTermDialog
        open={createOpen}
        domainId={domainId}
        onClose={() => setCreateOpen(false)}
      />
      <DomainDialog
        open={editing}
        onClose={() => setEditing(false)}
        initial={{
          domainId,
          name: domain.data.name,
          description: domain.data.description,
        }}
      />
      <DiscardDomainConfirm
        open={discarding}
        domainId={domainId}
        name={domain.data.name}
        onClose={() => setDiscarding(false)}
        onDiscarded={() => {
          void navigate('/vocabulary');
        }}
      />
    </div>
  );
}
