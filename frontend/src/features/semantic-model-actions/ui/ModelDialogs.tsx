import { zodResolver } from '@hookform/resolvers/zod';
import { useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import type { Model } from '@/entities/semantic';
import { normalizeError } from '@/shared/api/error';
import { Button, ConfirmDialog, Dialog, Input, Textarea } from '@/shared/ui';

import { useChangeModel, useCreateModel, useDiscardModel } from '../api/mutation';

const modelSchema = z.object({
  name: z.string().min(1, 'Enter a name'),
  description: z.string(),
});

type ModelValues = z.infer<typeof modelSchema>;

const EMPTY_MODEL: ModelValues = { name: '', description: '' };

export interface CreateModelDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated?: (modelId: string) => void;
}

/**
 * Renders the semantic model creation form.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function CreateModelDialog({ open, onClose, onCreated }: CreateModelDialogProps) {
  const mutation = useCreateModel();
  const form = useForm<ModelValues>({
    resolver: zodResolver(modelSchema),
    defaultValues: EMPTY_MODEL,
  });

  useEffect(() => {
    if (open) {
      form.reset(EMPTY_MODEL);
    }
  }, [open, form]);

  return (
    <Dialog
      open={open}
      title="New model"
      description="A model groups the entities and relationships of one business area."
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
                onSuccess: (modelId) => {
                  onClose();
                  onCreated?.(modelId);
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
          <Input placeholder="Sales analytics" {...form.register('name')} />
          {form.formState.errors.name !== undefined ? (
            <span className="text-xs text-danger">{form.formState.errors.name.message}</span>
          ) : null}
        </label>
        <label className="block space-y-1">
          <span className="text-sm text-text">Description</span>
          <Textarea rows={3} placeholder="optional" {...form.register('description')} />
        </label>
        {mutation.error !== null ? (
          <p className="text-sm text-danger">{normalizeError(mutation.error).detail}</p>
        ) : null}
      </div>
    </Dialog>
  );
}

export interface EditModelDialogProps {
  open: boolean;
  model: Model;
  onClose: () => void;
}

/**
 * Renders the model metadata form.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function EditModelDialog({ open, model, onClose }: EditModelDialogProps) {
  const mutation = useChangeModel(model.model_id);
  const form = useForm<ModelValues>({
    resolver: zodResolver(modelSchema),
    defaultValues: { name: model.name, description: model.description },
  });

  useEffect(() => {
    if (open) {
      form.reset({ name: model.name, description: model.description });
    }
  }, [open, form, model.name, model.description]);

  return (
    <Dialog
      open={open}
      title="Edit model"
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
          {form.formState.errors.name !== undefined ? (
            <span className="text-xs text-danger">{form.formState.errors.name.message}</span>
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

export interface DiscardModelConfirmProps {
  open: boolean;
  model: Model;
  onClose: () => void;
  onDiscarded?: () => void;
}

/**
 * Confirms the cascade deletion of a whole model.
 *
 * @param props Component props.
 * @returns The confirmation dialog.
 */
export function DiscardModelConfirm({
  open,
  model,
  onClose,
  onDiscarded,
}: DiscardModelConfirmProps) {
  const mutation = useDiscardModel(model.model_id);
  return (
    <ConfirmDialog
      open={open}
      danger
      title={`Delete ${model.name}?`}
      description="Every entity, relationship, diagram and node of this model is removed. This cannot be undone."
      confirmLabel="Delete model"
      loading={mutation.isPending}
      onCancel={onClose}
      onConfirm={() => {
        mutation.mutate(undefined, {
          onSuccess: () => {
            onClose();
            onDiscarded?.();
          },
        });
      }}
    />
  );
}
