import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import { catalogPatchSchema, type Catalog, type CatalogPatch } from '@/entities/catalog';
import { normalizeError } from '@/shared/api/error';
import { Button, ConfirmDialog, Dialog, Input, Textarea } from '@/shared/ui';

import { useChangeCatalog, useCreateCatalog, useDiscardCatalog } from '../api/mutation';

const createSchema = z.object({
  name: z.string().min(1, 'Enter a name'),
  description: z.string(),
});

type CreateValues = z.infer<typeof createSchema>;

export interface CreateCatalogDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated?: (catalogId: string) => void;
}

/**
 * Renders the catalog creation form.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function CreateCatalogDialog({ open, onClose, onCreated }: CreateCatalogDialogProps) {
  const mutation = useCreateCatalog();
  const form = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: { name: '', description: '' },
  });

  return (
    <Dialog
      open={open}
      title="New catalog"
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
                onSuccess: (catalogId) => {
                  form.reset();
                  onCreated?.(catalogId);
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

export interface EditCatalogDialogProps {
  open: boolean;
  catalog: Catalog;
  onClose: () => void;
}

/**
 * Renders the catalog edit form.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function EditCatalogDialog({ open, catalog, onClose }: EditCatalogDialogProps) {
  const mutation = useChangeCatalog(catalog.catalog_id);
  const form = useForm<CatalogPatch>({
    resolver: zodResolver(catalogPatchSchema),
    defaultValues: { name: catalog.name, description: catalog.description },
  });

  return (
    <Dialog
      open={open}
      title="Edit catalog"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={mutation.isPending}
            onClick={form.handleSubmit((values) => {
              mutation.mutate(values, { onSuccess: onClose });
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

export interface DiscardCatalogConfirmProps {
  open: boolean;
  catalog: Catalog;
  onClose: () => void;
  onDiscarded: () => void;
}

/**
 * Confirms the soft delete of a catalog.
 *
 * @param props Component props.
 * @returns The confirmation dialog.
 */
export function DiscardCatalogConfirm({
  open,
  catalog,
  onClose,
  onDiscarded,
}: DiscardCatalogConfirmProps) {
  const mutation = useDiscardCatalog(catalog.catalog_id);

  return (
    <ConfirmDialog
      open={open}
      danger
      title="Delete catalog"
      description={`Deletes catalog "${catalog.name}" with all its schemas, tables and fields.`}
      confirmLabel="Delete"
      loading={mutation.isPending}
      onCancel={onClose}
      onConfirm={() => {
        mutation.mutate(undefined, { onSuccess: onDiscarded });
      }}
    />
  );
}
