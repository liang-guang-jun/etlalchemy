import { Columns3, Database, Folder, Plus, Table2, Unlink } from 'lucide-react';
import { Link } from 'react-router';

import type { Term, TermLink } from '@/entities/term';
import { catalogPath, columnPath, schemaPath, tablePath } from '@/shared/lib/catalog-routes';
import { Badge, Button } from '@/shared/ui';

import { useUnlinkTerm } from '../api/mutation';

/** Icon per linked object kind, mirroring the picker levels. */
const KIND_ICONS = {
  catalog: Database,
  schema: Folder,
  table: Table2,
  field: Columns3,
} as const;

/**
 * Returns the catalog page of a resolved link.
 *
 * @param link Link as stored on the term.
 * @returns The href, or `null` when the ids needed to build it are missing.
 */
function linkHref(link: TermLink): string | null {
  if (link.status === 'dangling') {
    return null;
  }
  const catalogId = link.catalog_id ?? (link.target_kind === 'catalog' ? link.target_id : null);
  if (catalogId === null || catalogId === undefined) {
    return null;
  }
  if (link.target_kind === 'catalog') {
    return catalogPath(catalogId);
  }
  if (link.schema_id === null || link.schema_id === undefined) {
    return null;
  }
  if (link.target_kind === 'schema') {
    return schemaPath(catalogId, link.schema_id);
  }
  if (link.table_id === null || link.table_id === undefined) {
    return null;
  }
  if (link.target_kind === 'table') {
    return tablePath(catalogId, link.schema_id, link.table_id);
  }
  if (link.target_kind === 'field') {
    return columnPath(catalogId, link.schema_id, link.table_id, link.field_name);
  }
  return null;
}

export interface TermLinksListProps {
  domainId: string;
  term: Term;
  /** Unlinking is only allowed while the term is a draft. */
  editable: boolean;
  onRequestLink: () => void;
}

/**
 * Renders the catalog links of a term with a hover-to-unlink action.
 *
 * @param props Component props.
 * @returns The link list or its empty state.
 */
export function TermLinksList({ domainId, term, editable, onRequestLink }: TermLinksListProps) {
  const mutation = useUnlinkTerm(domainId, term.term_id);
  const addButton = (
    <Button
      size="sm"
      variant="ghost"
      icon={<Plus className="size-3.5" />}
      disabled={!editable}
      onClick={onRequestLink}
    >
      Link object
    </Button>
  );

  if (term.links.length === 0) {
    return (
      <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 rounded-lg border border-dashed border-border-strong px-4 py-6">
        <p className="text-sm text-text-secondary">
          No catalog objects linked yet.
          <span className="ml-1 text-xs text-text-disabled">
            Link a table or a field to surface the term in the catalog.
          </span>
        </p>
        {addButton}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-end">{addButton}</div>
      <ul className="divide-y divide-border-base overflow-hidden rounded-lg border border-border-base">
        {term.links.map((link) => {
          const key = `${link.target_kind}:${link.target_id}:${link.field_name}`;
          const label = link.target_name ?? link.target_id;
          const KindIcon =
            KIND_ICONS[link.target_kind as keyof typeof KIND_ICONS] ?? KIND_ICONS.catalog;
          const href = linkHref(link);
          // The resolver already ends a field name with the field.
          const suffix =
            link.field_name !== '' && link.target_name === null ? `.${link.field_name}` : '';
          const content = (
            <>
              <span className="shrink-0 text-text-secondary" title={link.target_kind}>
                <KindIcon className="size-4" aria-hidden="true" />
              </span>
              <span className="min-w-0 flex-1 truncate text-sm text-text-primary">
                {label}
                {suffix}
              </span>
            </>
          );
          return (
            <li
              key={key}
              className="group flex items-center gap-3 px-4 py-3 transition-colors hover:bg-bg-hover"
            >
              {href === null ? (
                <span className="flex min-w-0 flex-1 items-center gap-3">{content}</span>
              ) : (
                <Link
                  to={href}
                  title={`Open ${link.target_kind} in the catalog`}
                  className="flex min-w-0 flex-1 items-center gap-3 rounded-sm hover:underline"
                >
                  {content}
                </Link>
              )}
              {link.status === 'dangling' ? <Badge tone="danger">dangling</Badge> : null}
              {editable ? (
                <button
                  type="button"
                  aria-label={`Unlink ${label}`}
                  title="Unlink"
                  disabled={mutation.isPending}
                  onClick={() => {
                    mutation.mutate({
                      target_id: link.target_id,
                      target_kind: link.target_kind,
                      field_name: link.field_name,
                    });
                  }}
                  className="flex size-7 shrink-0 items-center justify-center rounded-md text-text-disabled transition-colors hover:bg-danger/10 hover:text-danger disabled:cursor-not-allowed"
                >
                  <Unlink className="size-3.5" aria-hidden="true" />
                </button>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
