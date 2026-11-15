import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import { normalizeError } from '@/shared/api/error';
import { Button, ConfirmDialog, Dialog, Input } from '@/shared/ui';

import { useChangeTable, useCreateTable, useDiscardTable } from '../api/mutation';

const nameSchema = z.object({ name: z.string().min(1, 'Enter a name') });

type NameValues = z.infer<typeof nameSchema>;

export interface CreateTableDialogProps {
  open: boolean;
  catalogId: string;
  schema: string;
  onClose: () => void;
  onCreated?: (tableId: string) => void;
}

/**
 * Renders the table creation form.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function CreateTableDialog({
  open,
  catalogId,
  schema,
  onClose,
  onCreated,
}: CreateTableDialogProps) {
  const mutation = useCreateTable(catalogId, schema);
  const form = useForm<NameValues>({
    resolver: zodResolver(nameSchema),
    defaultValues: { name: '' },
  });

  return (
    <Dialog
      open={open}
      title={`New table in ${schema}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={mutation.isPending}
            onClick={form.handleSubmit((values) => {
              mutation.mutate(values.name, {
                onSuccess: (tableId) => {
                  form.reset();
                  onCreated?.(tableId);
                  onClose();
                },
              });
            })}
          >
            Create
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <label className="block space-y-1">
          <span className="text-sm text-text">Table name</span>
          <Input {...form.register('name')} />
          {form.formState.errors.name !== undefined ? (
            <span className="text-sm text-danger">{form.formState.errors.name.message}</span>
          ) : null}
        </label>
        {mutation.error !== null ? (
          <p className="text-sm text-danger">{normalizeError(mutation.error).detail}</p>
        ) : null}
      </div>
    </Dialog>
  );
}

export interface RenameTableDialogProps {
  open: boolean;
  catalogId: string;
  schema: string;
  table: string;
  name: string;
  onClose: () => void;
  onRenamed?: (newName: string) => void;
}

/**
 * Renders the table rename form.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function RenameTableDialog({
  open,
  catalogId,
  schema,
  table,
  name,
  onClose,
  onRenamed,
}: RenameTableDialogProps) {
  const mutation = useChangeTable(catalogId, schema, table);
  const form = useForm<NameValues>({
    resolver: zodResolver(nameSchema),
    defaultValues: { name },
  });

  return (
    <Dialog
      open={open}
      title="Rename table"
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
                { name: values.name },
                {
                  onSuccess: () => {
                    onRenamed?.(values.name);
                    onClose();
                  },
                },
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
          <span className="text-sm text-text">Table name</span>
          <Input {...form.register('name')} />
          {form.formState.errors.name !== undefined ? (
            <span className="text-sm text-danger">{form.formState.errors.name.message}</span>
          ) : null}
        </label>
        {mutation.error !== null ? (
          <p className="text-sm text-danger">{normalizeError(mutation.error).detail}</p>
        ) : null}
      </div>
    </Dialog>
  );
}

export interface DiscardTableConfirmProps {
  open: boolean;
  catalogId: string;
  schema: string;
  table: string;
  onClose: () => void;
  onDiscarded: () => void;
}

/**
 * Confirms the soft delete of a table.
 *
 * @param props Component props.
 * @returns The confirmation dialog.
 */
export function DiscardTableConfirm({
  open,
  catalogId,
  schema,
  table,
  onClose,
  onDiscarded,
}: DiscardTableConfirmProps) {
  const mutation = useDiscardTable(catalogId, schema, table);

  return (
    <ConfirmDialog
      open={open}
      danger
      title="Delete table"
      description={`Deletes table "${table}" and all its fields.`}
      confirmLabel="Delete"
      loading={mutation.isPending}
      onCancel={onClose}
      onConfirm={() => {
        mutation.mutate(undefined, { onSuccess: onDiscarded });
      }}
    />
  );
}
