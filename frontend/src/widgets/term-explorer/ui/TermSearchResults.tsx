import { Link } from 'react-router';

import { useTermSearch } from '@/entities/term';
import { termPath } from '@/shared/lib/vocabulary-routes';
import { Badge, ColorDot, Skeleton, type BadgeTone } from '@/shared/ui';

export interface TermSearchResultsProps {
  /** Raw search text; every non-empty query runs. */
  query: string;
}

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
 * Renders a flat list of the terms that match the search text, with the domain
 * and path of every hit as its hint.
 *
 * @param props Component props.
 * @returns The search result list.
 */
export function TermSearchResults({ query }: TermSearchResultsProps) {
  const { data, isPending, isError } = useTermSearch(query);

  if (isPending) {
    return (
      <div className="p-2">
        <Skeleton lines={4} />
      </div>
    );
  }
  if (isError) {
    return <p className="px-2 py-4 text-xs text-text-secondary">Search failed.</p>;
  }

  const rows = data ?? [];
  if (rows.length === 0) {
    return (
      <p className="px-2 py-4 text-xs text-text-secondary">
        No term matches “{query.trim()}”. Search looks at names, definitions and aliases across
        every domain.
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-0.5 p-1" aria-label="Term search results">
      {rows.map((row) => (
        <li key={row.term_id}>
          <Link
            to={termPath(row.domain_id, row.term_id)}
            className="flex flex-col gap-0.5 rounded-sm px-2 py-1.5 transition-colors hover:bg-bg-hover"
          >
            <span className="flex items-center gap-2 text-sm font-medium text-text-primary">
              <ColorDot color={row.color} />
              <span className="truncate">{row.term_name}</span>
              <Badge tone={statusTone(row.status)}>{row.status}</Badge>
            </span>
            <span className="truncate pl-5 text-xs text-text-disabled">
              {row.domain_name} / {row.term_path}
              {row.matched_alias === null ? '' : ` · matched alias “${row.matched_alias}”`}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
