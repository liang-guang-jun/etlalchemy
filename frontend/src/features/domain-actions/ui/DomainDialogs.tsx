import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import { normalizeError } from '@/shared/api/error';
import { Button, ConfirmDialog, Dialog, Input, Textarea } from '@/shared/ui';

import { useChangeDomain, useCreateDomain, useDiscardDomain } from '../api/mutation';

const formSchema = z.object({
  name: z.string().min(1, 'Enter a name'),
  description: z.string(),
});

type FormValues = z.infer<typeof formSchema>;

export interface DomainDialogProps {
  open: boolean;
  onClose: () => void;
  initial?: { domainId: string; name: string; description: string };
}

/**
 * Creates a domain or edits an existing one.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function DomainDialog({ open, onClose, initial }: DomainDialogProps) {
  const create = useCreateDomain();
  const change = useChangeDomain(initial?.domainId ?? '');
  const mutation = initial === undefined ? create : change;
  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: { name: initial?.name ?? '', description: initial?.description ?? '' },
  });

  return (
    <Dialog
      open={open}
      title={initial === undefined ? 'New domain' : 'Edit domain'}
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
                  form.reset();
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

export interface DiscardDomainConfirmProps {
  open: boolean;
  domainId: string;
  name: string;
  onClose: () => void;
  onDiscarded: () => void;
}

/**
 * Confirms the deletion of a domain.
 *
 * @param props Component props.
 * @returns The confirmation dialog.
 */
export function DiscardDomainConfirm({
  open,
  domainId,
  name,
  onClose,
  onDiscarded,
}: DiscardDomainConfirmProps) {
  const mutation = useDiscardDomain(domainId);

  return (
    <ConfirmDialog
      open={open}
      danger
      title="Delete domain"
      description={`Deletes domain "${name}" and all its terms.`}
      confirmLabel="Delete"
      loading={mutation.isPending}
      onCancel={onClose}
      onConfirm={() => {
        mutation.mutate(undefined, { onSuccess: onDiscarded });
      }}
    />
  );
}
