import { useState, type ReactNode } from 'react';
import { Unlink } from 'lucide-react';
import { Link } from 'react-router';

import { useTermsForTarget, type TermSummary } from '@/entities/term';
import { termPath } from '@/shared/lib/vocabulary-routes';
import {
  Badge,
  Button,
  ColorDot,
  EmptyState,
  ErrorState,
  Skeleton,
  type BadgeTone,
} from '@/shared/ui';

import { useUnlinkTerm } from '../api/mutation';
import { TermLinkDialog } from './TermLinkDialog';

/** Badge tint per lifecycle status. */
const STATUS_TONES: Record<string, BadgeTone> = {
  draft: 'neutral',
  approved: 'success',
  deprecated: 'danger',
};

export interface LinkedTermsListProps {
  /** Id of the catalog, schema or table the terms are linked to. */
  targetId: string;
  /** Kind of the linked object. */
  targetKind: 'catalog' | 'schema' | 'table' | 'field';
  /** Name of the field when {@link targetKind} is `field`. */
  fieldName?: string;
}

interface LinkedTermRowProps {
  term: TermSummary;
  targetId: string;
  targetKind: 'catalog' | 'schema' | 'table' | 'field';
  fieldName: string;
  /** Called after the unlink is recorded, so the list can refresh itself. */
  onChanged: () => void;
}

/**
 * Renders one linked term with the action that removes the link.
 *
 * Only draft terms can be unlinked; the button stays visible but disabled so
 * the behaviour is discoverable instead of silently missing.
 *
 * @param props Component props.
 * @returns The term row.
 */
function LinkedTermRow({ term, targetId, targetKind, fieldName, onChanged }: LinkedTermRowProps) {
  const mutation = useUnlinkTerm(term.domain_id, term.term_id);
  const editable = term.status === 'draft';

  return (
    <li className="group flex items-center gap-3 px-4 py-3 transition-colors hover:bg-bg-hover">
      <ColorDot color={term.color} />
      <span className="flex min-w-0 flex-1 flex-col">
        <Link
          to={termPath(term.domain_id, term.term_id)}
          className="truncate text-sm font-medium text-text-primary hover:underline"
        >
          {term.name}
        </Link>
        <span className="truncate font-mono text-[11px] text-text-disabled">{term.path}</span>
      </span>
      <Badge tone={STATUS_TONES[term.status] ?? 'neutral'}>{term.status}</Badge>
      <button
        type="button"
        aria-label={`Unlink ${term.name}`}
        title={editable ? 'Unlink' : 'Only draft terms can be unlinked'}
        disabled={!editable || mutation.isPending}
        onClick={() => {
          mutation.mutate(
            {
              target_id: targetId,
              target_kind: targetKind,
              field_name: fieldName,
            },
            { onSuccess: onChanged },
          );
        }}
        className="flex size-7 shrink-0 items-center justify-center rounded-md text-text-disabled transition-colors hover:bg-danger/10 hover:text-danger disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-text-disabled"
      >
        <Unlink className="size-3.5" aria-hidden="true" />
      </button>
    </li>
  );
}

/**
 * Lists the vocabulary terms that point at one catalog object.
 *
 * The header offers the link action, so every level — catalog, schema, table and
 * field — is linked the same way, and both actions refresh this list as soon as
 * the server accepted them.
 *
 * @param props Component props.
 * @returns The linked terms list or its empty state.
 */
export function LinkedTermsList({ targetId, targetKind, fieldName = '' }: LinkedTermsListProps) {
  const [linking, setLinking] = useState(false);
  const { data, isPending, isError, error, refetch } = useTermsForTarget(
    targetId,
    targetKind,
    fieldName,
  );

  const refresh = (): void => {
    void refetch();
  };

  const body = (): ReactNode => {
    if (isPending) {
      return <Skeleton lines={4} />;
    }
    if (isError) {
      return (
        <ErrorState detail={error instanceof Error ? error.message : undefined} onRetry={refresh} />
      );
    }

    const terms = data ?? [];
    if (terms.length === 0) {
      return (
        <EmptyState
          plain
          title="No linked terms"
          description={`No business term is linked to this ${targetKind} yet.`}
        />
      );
    }

    return (
      <ul className="divide-y divide-border-base overflow-hidden rounded-lg border border-border-base">
        {terms.map((term) => (
          <LinkedTermRow
            key={term.term_id}
            term={term}
            targetId={targetId}
            targetKind={targetKind}
            fieldName={fieldName}
            onChanged={refresh}
          />
        ))}
      </ul>
    );
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-medium tracking-wide text-text-secondary uppercase">
          Linked terms
        </h3>
        <Button size="sm" variant="secondary" onClick={() => setLinking(true)}>
          Link term
        </Button>
      </div>

      {body()}

      <TermLinkDialog
        open={linking}
        targetId={targetId}
        targetKind={targetKind}
        fieldName={fieldName}
        onClose={() => setLinking(false)}
        onLinked={refresh}
      />
    </div>
  );
}
