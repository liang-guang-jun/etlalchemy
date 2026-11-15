import { zodResolver } from '@hookform/resolvers/zod';
import { Controller, useForm } from 'react-hook-form';
import { z } from 'zod';

import { DataTypePicker, parseDataType, type Field } from '@/entities/field';
import { normalizeError } from '@/shared/api/error';
import { Button, ConfirmDialog, Dialog, Input } from '@/shared/ui';

import { useAddField, useChangeField, useDiscardField, useRenameField } from '../api/mutation';

const addSchema = z.object({
  name: z.string().min(1, 'Enter a field name'),
  data_type: z.string().refine((value) => parseDataType(value) !== null, {
    message: 'Choose a valid data type',
  }),
  nullable: z.boolean(),
});

type AddValues = z.infer<typeof addSchema>;

export interface FieldDialogTarget {
  catalogId: string;
  schema: string;
  table: string;
}

export interface AddFieldDialogProps {
  open: boolean;
  target: FieldDialogTarget;
  onClose: () => void;
}

/**
 * Renders the field creation form.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function AddFieldDialog({ open, target, onClose }: AddFieldDialogProps) {
  const mutation = useAddField(target);
  const form = useForm<AddValues>({
    resolver: zodResolver(addSchema),
    defaultValues: { name: '', data_type: 'varchar(255)', nullable: true },
  });

  return (
    <Dialog
      open={open}
      title="Add field"
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
                { name: values.name, dataType: values.data_type, nullable: values.nullable },
                {
                  onSuccess: () => {
                    form.reset();
                    onClose();
                  },
                },
              );
            })}
          >
            Add
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <label className="block space-y-1">
          <span className="text-sm text-text">Field name</span>
          <Input {...form.register('name')} />
          {form.formState.errors.name !== undefined ? (
            <span className="text-sm text-danger">{form.formState.errors.name.message}</span>
          ) : null}
        </label>
        <div className="space-y-1">
          <span className="text-sm text-text">Data type</span>
          <Controller
            control={form.control}
            name="data_type"
            render={({ field }) => <DataTypePicker value={field.value} onChange={field.onChange} />}
          />
          {form.formState.errors.data_type !== undefined ? (
            <span className="text-sm text-danger">{form.formState.errors.data_type.message}</span>
          ) : null}
        </div>
        <label className="flex items-center gap-2 text-sm text-text">
          <input type="checkbox" {...form.register('nullable')} />
          Nullable
        </label>
        {mutation.error !== null ? (
          <p className="text-sm text-danger">{normalizeError(mutation.error).detail}</p>
        ) : null}
      </div>
    </Dialog>
  );
}

export interface EditFieldDialogProps {
  open: boolean;
  target: FieldDialogTarget;
  field: Field;
  onClose: () => void;
}

/**
 * Renders the field type/nullability form.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function EditFieldDialog({ open, target, field, onClose }: EditFieldDialogProps) {
  const mutation = useChangeField(target);
  const form = useForm<{ data_type: string; nullable: boolean }>({
    defaultValues: { data_type: field.data_type, nullable: field.nullable },
  });

  return (
    <Dialog
      open={open}
      title={`Edit field ${field.name}`}
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
                { fieldName: field.name, data_type: values.data_type, nullable: values.nullable },
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
        <div className="space-y-1">
          <span className="text-sm text-text">Data type</span>
          <Controller
            control={form.control}
            name="data_type"
            render={({ field: controlled }) => (
              <DataTypePicker value={controlled.value} onChange={controlled.onChange} />
            )}
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-text">
          <input type="checkbox" {...form.register('nullable')} />
          Nullable
        </label>
        {mutation.error !== null ? (
          <p className="text-sm text-danger">{normalizeError(mutation.error).detail}</p>
        ) : null}
      </div>
    </Dialog>
  );
}

export interface RenameFieldDialogProps {
  open: boolean;
  target: FieldDialogTarget;
  field: Field;
  onClose: () => void;
}

/**
 * Renders the field rename form.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function RenameFieldDialog({ open, target, field, onClose }: RenameFieldDialogProps) {
  const mutation = useRenameField(target);
  const form = useForm<{ name: string }>({
    resolver: zodResolver(z.object({ name: z.string().min(1, 'Enter a field name') })),
    defaultValues: { name: field.name },
  });

  return (
    <Dialog
      open={open}
      title="Rename field"
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
                { fieldName: field.name, newName: values.name },
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
          <span className="text-sm text-text">New field name</span>
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

export interface DiscardFieldConfirmProps {
  open: boolean;
  target: FieldDialogTarget;
  field: Field;
  onClose: () => void;
}

/**
 * Confirms the removal of a field.
 *
 * @param props Component props.
 * @returns The confirmation dialog.
 */
export function DiscardFieldConfirm({ open, target, field, onClose }: DiscardFieldConfirmProps) {
  const mutation = useDiscardField(target);

  return (
    <ConfirmDialog
      open={open}
      danger
      title="Delete field"
      description={`Deletes field "${field.name}".`}
      confirmLabel="Delete"
      loading={mutation.isPending}
      onCancel={onClose}
      onConfirm={() => {
        mutation.mutate(field.name, { onSuccess: onClose });
      }}
    />
  );
}
