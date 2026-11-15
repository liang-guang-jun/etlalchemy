import { useState } from 'react';
import { BookOpen, Plus } from 'lucide-react';
import { Link } from 'react-router';

import { useDomains, type Domain } from '@/entities/domain';
import { DomainDialog } from '@/features/domain-actions';
import { domainPath } from '@/shared/lib/vocabulary-routes';
import { Button, EmptyState, ErrorState, PageHeader, Skeleton } from '@/shared/ui';

interface DomainCardProps {
  domain: Domain;
}

/**
 * Renders one domain tile of the overview.
 *
 * @param props Component props.
 * @returns The card element.
 */
function DomainCard({ domain }: DomainCardProps) {
  return (
    <li>
      <Link
        to={domainPath(domain.domain_id)}
        className="group flex h-full flex-col gap-2 rounded-md border border-border-base bg-bg-surface p-4 transition-colors hover:border-border-strong hover:bg-bg-hover"
      >
        <span className="flex items-center gap-2 text-sm font-semibold text-text-primary">
          <BookOpen className="size-4 shrink-0 text-text-secondary" aria-hidden="true" />
          <span className="truncate">{domain.name}</span>
        </span>
        <span className="line-clamp-2 min-h-[32px] text-sm text-text-secondary">
          {domain.description || 'No description'}
        </span>
        <span className="text-xs font-medium text-text-secondary transition-colors group-hover:text-text-primary">
          Open domain →
        </span>
      </Link>
    </li>
  );
}

/**
 * Renders the overview panel of the business-terms workspace.
 *
 * @returns The domain overview page.
 */
export default function VocabularyListPage() {
  const { data, isPending, isError, error, refetch } = useDomains();
  const [createOpen, setCreateOpen] = useState(false);

  return (
    <div>
      <PageHeader
        title="Business terms"
        description="Browse every glossary domain, its term tree and the catalog objects each term is linked to."
        actions={
          <Button
            icon={<Plus className="size-4" />}
            onClick={() => {
              setCreateOpen(true);
            }}
          >
            New domain
          </Button>
        }
      />

      {isPending ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Skeleton lines={4} />
          <Skeleton lines={4} />
          <Skeleton lines={4} />
        </div>
      ) : isError ? (
        <ErrorState
          detail={error instanceof Error ? error.message : undefined}
          onRetry={() => {
            void refetch();
          }}
        />
      ) : (data ?? []).length === 0 ? (
        <EmptyState
          icon={<BookOpen className="size-10" aria-hidden="true" />}
          title="No domains yet"
          description="Create the first domain to organise terms."
          action={
            <Button
              icon={<Plus className="size-4" />}
              onClick={() => {
                setCreateOpen(true);
              }}
            >
              New domain
            </Button>
          }
          className="py-20"
        />
      ) : (
        <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {(data ?? []).map((domain) => (
            <DomainCard key={domain.domain_id} domain={domain} />
          ))}
        </ul>
      )}

      <DomainDialog open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}
