import { Fragment } from 'react';
import { ChevronRight } from 'lucide-react';
import { Link } from 'react-router';

/** One segment of a breadcrumb trail. */
export interface BreadcrumbItem {
  label: string;
  /** Target of the segment; the last segment is usually plain text. */
  to?: string;
}

export interface BreadcrumbsProps {
  items: BreadcrumbItem[];
}

/**
 * Renders a compact breadcrumb trail whose parent segments are links.
 *
 * @param props Component props.
 * @returns The breadcrumb element.
 */
export function Breadcrumbs({ items }: BreadcrumbsProps) {
  return (
    <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1 text-sm">
      {items.map((item, index) => (
        <Fragment key={`${item.label}-${String(index)}`}>
          {index > 0 ? (
            <ChevronRight className="size-3.5 shrink-0 text-text-disabled" aria-hidden="true" />
          ) : null}
          {item.to === undefined ? (
            <span className="truncate font-medium text-text-primary">{item.label}</span>
          ) : (
            <Link
              to={item.to}
              className="truncate rounded-sm text-text-secondary transition-colors hover:text-text-primary"
            >
              {item.label}
            </Link>
          )}
        </Fragment>
      ))}
    </nav>
  );
}
