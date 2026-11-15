import { useState } from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { Tag } from 'lucide-react';
import { z } from 'zod';

import { CatalogObjectPicker, type CatalogObjectSelection } from './CatalogObjectPicker';
import { TermPicker, useTerms, type Term, type TermSummary } from '@/entities/term';
import { normalizeError } from '@/shared/api/error';
import { Button, ColorPicker, ConfirmDialog, Dialog, Input, Textarea } from '@/shared/ui';

import {
  useChangeTerm,
  useCreateTerm,
  useDiscardTerm,
  useLinkTerm,
  useMoveTerm,
} from '../api/mutation';

const createSchema = z.object({
  name: z.string().min(1, 'Enter a name'),
  definition: z.string().min(1, 'Enter a definition'),
  aliases: z.string(),
});

type CreateValues = z.infer<typeof createSchema>;

const splitAliases = (value: string): string[] =>
  value
    .split(',')
    .map((alias) => alias.trim())
    .filter((alias) => alias !== '');

export interface CreateTermDialogProps {
  open: boolean;
  domainId: string;
  parentPath?: string;
  onClose: () => void;
}

/**
 * Renders the term creation form.
 *
 * The parent is picked from the domain tree instead of being typed as a path.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function CreateTermDialog({ open, domainId, parentPath, onClose }: CreateTermDialogProps) {
  const mutation = useCreateTerm(domainId);
  const terms = useTerms(domainId);
  const [parent, setParent] = useState<TermSummary | null>(null);
  const [color, setColor] = useState('');
  const [picking, setPicking] = useState(false);
  const form = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: { name: '', definition: '', aliases: '' },
  });

  const presetParent = (terms.data ?? []).find((term) => term.path === parentPath);
  const selected = parent ?? presetParent ?? null;

  return (
    <>
      <Dialog
        open={open}
        title="New term"
        onClose={onClose}
        footer={
          <>
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button
              loading={mutation.isPending}
              onClick={form.handleSubmit((values) => {
                mutation.mutate(
                  {
                    name: values.name,
                    definition: values.definition,
                    aliases: splitAliases(values.aliases),
                    parent: selected === null ? null : selected.term_id,
                    color,
                  },
                  {
                    onSuccess: () => {
                      form.reset();
                      setParent(null);
                      setColor('');
                      onClose();
                    },
                  },
                );
              })}
            >
              Create
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <label className="block space-y-1">
            <span className="text-sm text-text">Name</span>
            <Input {...form.register('name')} />
            {form.formState.errors.name !== undefined ? (
              <span className="text-sm text-danger">{form.formState.errors.name.message}</span>
            ) : null}
          </label>
          <label className="block space-y-1">
            <span className="text-sm text-text">Definition</span>
            <Textarea rows={3} {...form.register('definition')} />
            {form.formState.errors.definition !== undefined ? (
              <span className="text-sm text-danger">
                {form.formState.errors.definition.message}
              </span>
            ) : null}
          </label>
          <label className="block space-y-1">
            <span className="text-sm text-text">Aliases (comma separated)</span>
            <Input {...form.register('aliases')} />
          </label>
          <div className="space-y-1">
            <span className="text-sm text-text">Parent term</span>
            <div className="flex items-center gap-2">
              <span className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-md border border-border-base bg-bg-canvas px-3 text-sm text-text-secondary">
                <Tag className="size-3.5 shrink-0" aria-hidden="true" />
                <span className="truncate">{selected === null ? 'Top level' : selected.path}</span>
              </span>
              <Button variant="secondary" onClick={() => setPicking(true)}>
                Choose…
              </Button>
            </div>
          </div>
          <div className="space-y-1">
            <span className="text-sm text-text">Colour</span>
            <ColorPicker value={color} onChange={setColor} />
          </div>
          {mutation.error !== null ? (
            <p className="text-sm text-danger">{normalizeError(mutation.error).detail}</p>
          ) : null}
        </div>
      </Dialog>
      <TermPicker
        open={picking}
        domainId={domainId}
        title="Choose the parent term"
        allowTopLevel
        topLevelLabel="Create at the top level"
        onSelect={(term) => {
          setParent(term);
        }}
        onClose={() => setPicking(false)}
      />
    </>
  );
}

export interface EditTermDialogProps {
  open: boolean;
  domainId: string;
  term: Term;
  editable: boolean;
  onClose: () => void;
}

/**
 * Renders the term edit form; definition and aliases are locked outside drafts.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function EditTermDialog({ open, domainId, term, editable, onClose }: EditTermDialogProps) {
  const mutation = useChangeTerm(domainId, term.term_id);
  const [color, setColor] = useState(term.color);
  const form = useForm<{ name: string; definition: string; aliases: string }>({
    defaultValues: {
      name: term.name,
      definition: term.definition,
      aliases: term.aliases.join(', '),
    },
  });

  return (
    <Dialog
      open={open}
      title="Edit term"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={mutation.isPending}
            onClick={form.handleSubmit((values) => {
              const nextAliases = splitAliases(values.aliases);
              const added = nextAliases.filter((alias) => !term.aliases.includes(alias));
              const removed = term.aliases.filter((alias) => !nextAliases.includes(alias));
              mutation.mutate(
                {
                  name: values.name === term.name ? undefined : values.name,
                  definition:
                    editable && values.definition !== term.definition
                      ? values.definition
                      : undefined,
                  aliases_add: editable && added.length > 0 ? added : undefined,
                  aliases_remove: editable && removed.length > 0 ? removed : undefined,
                  color: color === term.color ? undefined : color,
                },
                { onSuccess: onClose },
              );
            })}
          >
            Save
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <label className="block space-y-1">
          <span className="text-sm text-text">Name</span>
          <Input {...form.register('name')} />
        </label>
        <label className="block space-y-1">
          <span className="text-sm text-text">Definition</span>
          <Textarea rows={4} disabled={!editable} {...form.register('definition')} />
          {!editable ? (
            <span className="text-xs text-warning">
              Approved terms can only be renamed, recoloured, moved or deprecated.
            </span>
          ) : null}
        </label>
        <label className="block space-y-1">
          <span className="text-sm text-text">Aliases (comma separated)</span>
          <Input disabled={!editable} {...form.register('aliases')} />
        </label>
        <div className="space-y-1">
          <span className="text-sm text-text">Colour</span>
          <ColorPicker value={color} onChange={setColor} />
          <span className="text-xs text-text-secondary">
            The colour only decorates the term in the tree and the tables.
          </span>
        </div>
        {mutation.error !== null ? (
          <p className="text-sm text-danger">{normalizeError(mutation.error).detail}</p>
        ) : null}
      </div>
    </Dialog>
  );
}

export interface MoveTermDialogProps {
  open: boolean;
  domainId: string;
  term: Term;
  onClose: () => void;
}

/**
 * Renders the "move under another parent" form.
 *
 * The new parent is picked from the domain tree, so no path is typed by hand.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function MoveTermDialog({ open, domainId, term, onClose }: MoveTermDialogProps) {
  const mutation = useMoveTerm(domainId);
  const terms = useTerms(domainId);
  // `undefined` means "nothing picked yet", `null` the explicit top level.
  const [parent, setParent] = useState<TermSummary | null | undefined>(undefined);
  const [picking, setPicking] = useState(false);

  const excluded = (terms.data ?? [])
    .filter((row) => row.term_id === term.term_id || row.path.startsWith(`${term.path}/`))
    .map((row) => row.term_id);

  return (
    <>
      <Dialog
        open={open}
        title="Move term"
        description={`Current parent: ${term.path.includes('/') ? term.path.slice(0, term.path.lastIndexOf('/')) : 'top level'}`}
        onClose={onClose}
        footer={
          <>
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button
              loading={mutation.isPending}
              disabled={parent === undefined}
              onClick={() => {
                mutation.mutate(
                  {
                    termId: term.term_id,
                    newParent: parent === null || parent === undefined ? null : parent.term_id,
                  },
                  { onSuccess: onClose },
                );
              }}
            >
              Move
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <div className="space-y-1">
            <span className="text-sm text-text">New parent</span>
            <div className="flex items-center gap-2">
              <span className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-md border border-border-base bg-bg-canvas px-3 text-sm text-text-secondary">
                <Tag className="size-3.5 shrink-0" aria-hidden="true" />
                <span className="truncate">
                  {parent === undefined
                    ? 'Nothing picked yet'
                    : parent === null
                      ? 'Top level'
                      : parent.path}
                </span>
              </span>
              <Button variant="secondary" onClick={() => setPicking(true)}>
                Choose…
              </Button>
            </div>
          </div>
          {mutation.error !== null ? (
            <p className="text-sm text-danger">{normalizeError(mutation.error).detail}</p>
          ) : null}
        </div>
      </Dialog>
      <TermPicker
        open={picking}
        domainId={domainId}
        title="Choose the new parent"
        excludeIds={excluded}
        allowTopLevel
        onSelect={(chosen) => {
          setParent(chosen);
        }}
        onClose={() => setPicking(false)}
      />
    </>
  );
}

export interface LinkTermDialogProps {
  open: boolean;
  domainId: string;
  term: Term;
  onClose: () => void;
}

/**
 * Links a term to a catalog object or to a table field.
 *
 * The target is picked with the catalog browser, so neither the kind nor the id
 * is typed by hand.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function LinkTermDialog({ open, domainId, term, onClose }: LinkTermDialogProps) {
  const mutation = useLinkTerm(domainId, term.term_id);
  const [selection, setSelection] = useState<CatalogObjectSelection | null>(null);
  const [picking, setPicking] = useState(false);

  return (
    <>
      <Dialog
        open={open}
        title="Link a catalog object"
        description="Browse catalogs, schemas, tables and fields, then pick the object to link."
        onClose={onClose}
        footer={
          <>
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button
              loading={mutation.isPending}
              disabled={selection === null}
              onClick={() => {
                if (selection === null) {
                  return;
                }
                mutation.mutate(
                  {
                    target_id: selection.targetId,
                    target_kind: selection.kind,
                    field_name: selection.fieldName,
                  },
                  { onSuccess: onClose },
                );
              }}
            >
              Link
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <div className="space-y-1">
            <span className="text-sm text-text">Catalog object</span>
            <div className="flex items-center gap-2">
              <span className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-md border border-border-base bg-bg-canvas px-3 text-sm text-text-secondary">
                <Tag className="size-3.5 shrink-0" aria-hidden="true" />
                <span className="truncate">
                  {selection === null ? 'Nothing picked yet' : selection.label}
                </span>
              </span>
              <Button variant="secondary" onClick={() => setPicking(true)}>
                Choose…
              </Button>
            </div>
          </div>
          {selection === null ? null : (
            <p className="font-mono text-xs text-text-disabled">
              {selection.kind}
              {selection.fieldName === '' ? '' : ` · ${selection.fieldName}`} · {selection.targetId}
            </p>
          )}
          {mutation.error !== null ? (
            <p className="text-sm text-danger">{normalizeError(mutation.error).detail}</p>
          ) : null}
        </div>
      </Dialog>
      <CatalogObjectPicker
        open={picking}
        onSelect={setSelection}
        onClose={() => setPicking(false)}
      />
    </>
  );
}

export interface DiscardTermConfirmProps {
  open: boolean;
  domainId: string;
  term: Term;
  onClose: () => void;
  onDiscarded: () => void;
}

/**
 * Confirms the deletion of a term and its descendants.
 *
 * @param props Component props.
 * @returns The confirmation dialog.
 */
export function DiscardTermConfirm({
  open,
  domainId,
  term,
  onClose,
  onDiscarded,
}: DiscardTermConfirmProps) {
  const mutation = useDiscardTerm(domainId);

  return (
    <ConfirmDialog
      open={open}
      danger
      title="Delete term"
      description={`Deletes term "${term.path}" and all its descendants.`}
      confirmLabel="Delete"
      loading={mutation.isPending}
      onCancel={onClose}
      onConfirm={() => {
        mutation.mutate(term.term_id, { onSuccess: onDiscarded });
      }}
    />
  );
}
