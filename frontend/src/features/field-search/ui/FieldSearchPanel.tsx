import { useState } from 'react';
import { Link } from 'react-router';

import { useFieldSearch } from '@/entities/field';
import { tablePath } from '@/shared/lib/catalog-routes';
import { Badge, Input, Skeleton } from '@/shared/ui';

export interface FieldSearchPanelProps {
  catalogId?: string;
}

/**
 * Searches fields across the catalog and links to their tables.
 *
 * @param props Component props.
 * @returns The search panel.
 */
export function FieldSearchPanel({ catalogId }: FieldSearchPanelProps) {
  const [term, setTerm] = useState('');
  const { data, isPending, isError } = useFieldSearch(term, catalogId);

  return (
    <div className="space-y-3">
      <Input
        placeholder="Search field, table or schema names (at least 2 characters)"
        value={term}
        onChange={(event) => {
          setTerm(event.target.value);
        }}
      />
      {term.trim().length < 2 ? (
        <p className="text-sm text-text-muted">Type at least 2 characters to search.</p>
      ) : isPending ? (
        <Skeleton lines={3} />
      ) : isError ? (
        <p className="text-sm text-danger">Search failed. Please try again.</p>
      ) : (data ?? []).length === 0 ? (
        <p className="text-sm text-text-muted">No matching fields.</p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {(data ?? []).map((result) => (
            <li key={`${result.table_id}:${result.field_name}`} className="px-3 py-2">
              <Link
                to={tablePath(result.catalog_id, result.schema_name, result.table_name)}
                className="flex flex-wrap items-center gap-2 text-sm hover:text-accent"
              >
                <span className="font-medium text-text">{result.field_name}</span>
                <Badge tone="neutral">{result.data_type}</Badge>
                <span className="text-text-muted">
                  {result.schema_name}.{result.table_name}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
