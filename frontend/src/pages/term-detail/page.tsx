import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router';

import { useDomain } from '@/entities/domain';
import { useTerm, useTerms } from '@/entities/term';
import {
  AliasTags,
  DiscardTermConfirm,
  EditTermDialog,
  LinkTermDialog,
  MoveTermDialog,
  TermColorPicker,
  TermHeaderActions,
  TermLinksList,
  TermStatusMenu,
  useChangeTerm,
} from '@/features/term-actions';
import { domainPath, termPath } from '@/shared/lib/vocabulary-routes';
import { CommentPanelBody } from '@/features/comment-threads';
import { Breadcrumbs, ErrorState, Skeleton, Tabs, type BreadcrumbItem } from '@/shared/ui';
// Imported by path so the markdown bundle stays in this lazily loaded page.
import { MarkdownEditor } from '@/shared/ui/markdown-editor';

/**
 * Renders the detail panel of one term.
 *
 * The lifecycle badge opens the allowed transitions, aliases are inline pills and
 * the definition is a markdown document that switches to an editor in place.
 *
 * @returns The term detail page.
 */
export default function TermDetailPage() {
  const { domainId = '', termId = '' } = useParams<{
    domainId: string;
    termId: string;
  }>();
  const navigate = useNavigate();
  const domain = useDomain(domainId);
  const term = useTerm(domainId, termId);
  const siblings = useTerms(domainId);
  const definitionMutation = useChangeTerm(domainId, termId);
  const [tab, setTab] = useState<'definition' | 'links' | 'discussion'>('definition');
  const [editing, setEditing] = useState(false);
  const [moving, setMoving] = useState(false);
  const [linking, setLinking] = useState(false);
  const [discarding, setDiscarding] = useState(false);

  const breadcrumbs = useMemo<BreadcrumbItem[]>(() => {
    const items: BreadcrumbItem[] = [
      { label: 'Business terms', to: '/vocabulary' },
      { label: domain.data?.name ?? 'Domain', to: domainPath(domainId) },
    ];
    if (term.data === undefined) {
      return items;
    }
    const segments = term.data.path.split('/');
    const byPath = new Map((siblings.data ?? []).map((row) => [row.path, row.term_id]));
    let prefix = '';
    for (const segment of segments.slice(0, -1)) {
      prefix = prefix === '' ? segment : `${prefix}/${segment}`;
      const ancestorId = byPath.get(prefix);
      items.push(
        ancestorId === undefined
          ? { label: segment }
          : { label: segment, to: termPath(domainId, ancestorId) },
      );
    }
    items.push({ label: term.data.name });
    return items;
  }, [domain.data?.name, domainId, siblings.data, term.data]);

  if (term.isPending) {
    return <Skeleton lines={6} />;
  }
  if (term.isError || term.data === undefined) {
    return (
      <ErrorState
        detail={term.error instanceof Error ? term.error.message : undefined}
        onRetry={() => {
          void term.refetch();
        }}
      />
    );
  }

  const current = term.data;
  const draft = current.status === 'draft';

  return (
    <div className="mx-auto w-full max-w-4xl">
      <header className="mb-6 flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="flex min-w-0 items-center gap-2">
            <Breadcrumbs items={breadcrumbs} />
            <span className="shrink-0 rounded bg-bg-hover-subtle px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-text-disabled uppercase">
              Term
            </span>
          </span>
          <TermHeaderActions
            canLink={draft}
            onEdit={() => {
              setEditing(true);
            }}
            onMove={() => {
              setMoving(true);
            }}
            onLink={() => {
              setLinking(true);
            }}
            onDelete={() => {
              setDiscarding(true);
            }}
          />
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <TermColorPicker domainId={domainId} term={current} />
          <h1 className="text-3xl leading-tight font-bold tracking-tight text-text-primary">
            {current.name}
          </h1>
          <TermStatusMenu domainId={domainId} term={current} />
        </div>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-text-secondary">Aliases:</span>
            <AliasTags domainId={domainId} term={current} editable={draft} />
          </div>
          <span className="font-mono text-xs text-text-disabled">{current.path}</span>
        </div>
      </header>

      <Tabs
        items={[
          { value: 'definition', label: 'Definition' },
          { value: 'links', label: 'Catalog links', count: current.links.length },
          { value: 'discussion', label: 'Discussion' },
        ]}
        value={tab}
        onChange={(value) => {
          setTab(
            value === 'links' ? 'links' : value === 'discussion' ? 'discussion' : 'definition',
          );
        }}
      />

      {tab === 'definition' ? (
        <div className="pt-4">
          <MarkdownEditor
            value={current.definition}
            editable={draft}
            saving={definitionMutation.isPending}
            label="Definition"
            onSave={(value) => {
              definitionMutation.mutate({ definition: value });
            }}
          />
        </div>
      ) : tab === 'discussion' ? (
        <div className="h-[36rem] pt-4">
          <CommentPanelBody target={{ type: 'term', id: current.term_id, label: current.path }} />
        </div>
      ) : (
        <div className="pt-4">
          <TermLinksList
            domainId={domainId}
            term={current}
            editable={draft}
            onRequestLink={() => {
              setLinking(true);
            }}
          />
        </div>
      )}

      <EditTermDialog
        open={editing}
        domainId={domainId}
        term={current}
        editable={draft}
        onClose={() => setEditing(false)}
      />
      <MoveTermDialog
        open={moving}
        domainId={domainId}
        term={current}
        onClose={() => setMoving(false)}
      />
      <LinkTermDialog
        open={linking}
        domainId={domainId}
        term={current}
        onClose={() => setLinking(false)}
      />
      <DiscardTermConfirm
        open={discarding}
        domainId={domainId}
        term={current}
        onClose={() => setDiscarding(false)}
        onDiscarded={() => {
          void navigate(domainPath(domainId));
        }}
      />
    </div>
  );
}
