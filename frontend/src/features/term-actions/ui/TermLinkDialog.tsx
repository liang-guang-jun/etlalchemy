import { useState } from 'react';
import { Tag } from 'lucide-react';

import { normalizeError } from '@/shared/api/error';
import { Button, Dialog } from '@/shared/ui';

import { useLinkTerm } from '../api/mutation';
import { TermTree, type TermSelection } from './TermTree';

/** Kinds a term can be linked to. */
export type LinkTargetKind = 'catalog' | 'schema' | 'table' | 'field';

export interface TermLinkDialogProps {
  open: boolean;
  /** Id of the catalog, schema or table, or of the owning table for a field. */
  targetId: string;
  /** Kind of the linked object. */
  targetKind: LinkTargetKind;
  /** Name of the field when {@link targetKind} is `field`. */
  fieldName?: string;
  onClose: () => void;
  /** Called after the link is recorded, so the caller can refresh its list. */
  onLinked?: () => void;
}

/**
 * Links one term of the vocabulary to a catalog object.
 *
 * The term is picked from the searchable vocabulary tree, which is the mirror
 * image of the catalog picker: either side of a link can be browsed, and a
 * keyword searches names, definitions and aliases across every domain.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function TermLinkDialog({
  open,
  targetId,
  targetKind,
  fieldName = '',
  onClose,
  onLinked,
}: TermLinkDialogProps) {
  const [picked, setPicked] = useState<TermSelection | null>(null);
  const mutation = useLinkTerm(picked?.domainId ?? '', picked?.termId ?? '');

  return (
    <Dialog
      open={open}
      title="Link a term"
      description="Browse the vocabulary or search it by name, definition or alias, then link the term."
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={mutation.isPending}
            disabled={picked === null}
            onClick={() => {
              if (picked === null) {
                return;
              }
              mutation.mutate(
                { target_id: targetId, target_kind: targetKind, field_name: fieldName },
                {
                  onSuccess: () => {
                    setPicked(null);
                    onLinked?.();
                    onClose();
                  },
                },
              );
            }}
          >
            Link
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <TermTree onPick={setPicked} />
        <div className="space-y-1">
          <span className="text-sm text-text">Term</span>
          <span className="flex h-9 min-w-0 items-center gap-2 rounded-md border border-border-base bg-bg-canvas px-3 text-sm text-text-secondary">
            <Tag className="size-3.5 shrink-0" aria-hidden="true" />
            <span className="truncate">
              {picked === null ? 'Nothing picked yet' : `${picked.domainName} / ${picked.path}`}
            </span>
          </span>
        </div>
        {mutation.error !== null ? (
          <p className="text-sm text-danger">{normalizeError(mutation.error).detail}</p>
        ) : null}
      </div>
    </Dialog>
  );
}
