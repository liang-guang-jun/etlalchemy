import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import { normalizeError } from '@/shared/api/error';
import { Button, ConfirmDialog, Dialog, Input, Textarea } from '@/shared/ui';

import { useChangeSchema, useCreateSchema, useDiscardSchema } from '../api/mutation';

const createSchema = z.object({
  name: z.string().min(1, 'Enter a name'),
  description: z.string(),
});

type CreateValues = z.infer<typeof createSchema>;

export interface SchemaDialogProps {
  open: boolean;
  catalogId: string;
  onClose: () => void;
  onCreated?: (schemaId: string) => void;
}

/**
 * Renders the schema creation form.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function CreateSchemaDialog({ open, catalogId, onClose, onCreated }: SchemaDialogProps) {
  const mutation = useCreateSchema(catalogId);
  const form = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: { name: '', description: '' },
  });

  return (
    <Dialog
      open={open}
      title="New schema"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={mutation.isPending}
            onClick={form.handleSubmit((values) => {
              mutation.mutate(values, {
                onSuccess: (schemaId) => {
                  form.reset();
                  onCreated?.(schemaId);
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
          <span className="text-sm text-text">Name</span>
          <Input {...form.register('name')} />
          {form.formState.errors.name !== undefined ? (
            <span className="text-sm text-danger">{form.formState.errors.name.message}</span>
          ) : null}
        </label>
        <label className="block space-y-1">
          <span className="text-sm text-text">Description</span>
          <Textarea rows={3} {...form.register('description')} />
        </label>
        {mutation.error !== null ? (
          <p className="text-sm text-danger">{normalizeError(mutation.error).detail}</p>
        ) : null}
      </div>
    </Dialog>
  );
}

export interface EditSchemaDialogProps {
  open: boolean;
  catalogId: string;
  schema: string;
  name: string;
  description: string;
  onClose: () => void;
  onRenamed?: (newName: string) => void;
}

/**
 * Renders the schema edit form.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function EditSchemaDialog({
  open,
  catalogId,
  schema,
  name,
  description,
  onClose,
  onRenamed,
}: EditSchemaDialogProps) {
  const mutation = useChangeSchema(catalogId, schema);
  const form = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: { name, description },
  });

  return (
    <Dialog
      open={open}
      title="Edit schema"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={mutation.isPending}
            onClick={form.handleSubmit((values) => {
              mutation.mutate(values, {
                onSuccess: () => {
                  if (values.name !== name) {
                    onRenamed?.(values.name);
                  }
                  onClose();
                },
              });
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
          <span className="text-sm text-text">Description</span>
          <Textarea rows={3} {...form.register('description')} />
        </label>
        {mutation.error !== null ? (
          <p className="text-sm text-danger">{normalizeError(mutation.error).detail}</p>
        ) : null}
      </div>
    </Dialog>
  );
}

export interface DiscardSchemaConfirmProps {
  open: boolean;
  catalogId: string;
  schema: string;
  onClose: () => void;
  onDiscarded: () => void;
}

/**
 * Confirms the soft delete of a schema.
 *
 * @param props Component props.
 * @returns The confirmation dialog.
 */
export function DiscardSchemaConfirm({
  open,
  catalogId,
  schema,
  onClose,
  onDiscarded,
}: DiscardSchemaConfirmProps) {
  const mutation = useDiscardSchema(catalogId, schema);

  return (
    <ConfirmDialog
      open={open}
      danger
      title="Delete schema"
      description={`Deletes schema "${schema}" with all its tables and fields.`}
      confirmLabel="Delete"
      loading={mutation.isPending}
      onCancel={onClose}
      onConfirm={() => {
        mutation.mutate(undefined, { onSuccess: onDiscarded });
      }}
    />
  );
}
