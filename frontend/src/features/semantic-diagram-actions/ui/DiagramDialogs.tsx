import { useEffect, useState } from 'react';

import type { Diagram } from '@/entities/semantic';
import { normalizeError } from '@/shared/api/error';
import { Button, ConfirmDialog, Dialog, Input } from '@/shared/ui';

import { useAddDiagram, useChangeDiagram, useRemoveDiagram } from '../api/mutation';

export interface DiagramDialogProps {
  open: boolean;
  modelId: string;
  /** Diagram to edit; omit to create a new one. */
  diagram?: Diagram;
  /** Sort hint offered for a new diagram. */
  nextOrder: number;
  onClose: () => void;
  onCreated?: (name: string) => void;
}

/**
 * Creates or edits a diagram: its name and its sort hint.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function DiagramDialog({
  open,
  modelId,
  diagram,
  nextOrder,
  onClose,
  onCreated,
}: DiagramDialogProps) {
  const editing = diagram !== undefined;
  const create = useAddDiagram(modelId);
  const change = useChangeDiagram(modelId, diagram?.name ?? '');
  const pending = editing ? change.isPending : create.isPending;
  const mutationError = editing ? change.error : create.error;

  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    setError(null);
    setName(diagram?.name ?? '');
  }, [open, diagram]);

  return (
    <Dialog
      open={open}
      title={editing ? 'Rename diagram' : 'New diagram'}
      description="A diagram is a canvas that shows the entities you place on it. Drag its tab to reorder it."
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={pending}
            onClick={() => {
              const trimmed = name.trim();
              if (trimmed === '' || trimmed.includes('/')) {
                setError('Enter a name; it cannot be blank or contain “/”');
                return;
              }
              setError(null);
              if (diagram !== undefined) {
                if (trimmed === diagram.name) {
                  onClose();
                  return;
                }
                change.mutate({ new_name: trimmed }, { onSuccess: onClose });
                return;
              }
              create.mutate(
                { name: trimmed, order: nextOrder },
                {
                  onSuccess: () => {
                    onClose();
                    onCreated?.(trimmed);
                  },
                },
              );
            }}
          >
            {editing ? 'Save' : 'Create'}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <label className="block space-y-1">
          <span className="text-sm text-text">Name</span>
          <Input
            placeholder="Sales overview"
            value={name}
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
        </label>
        {error !== null ? <p className="text-sm text-danger">{error}</p> : null}
        {mutationError !== null ? (
          <p className="text-sm text-danger">{normalizeError(mutationError).detail}</p>
        ) : null}
      </div>
    </Dialog>
  );
}

export interface RemoveDiagramConfirmProps {
  open: boolean;
  modelId: string;
  diagramName: string;
  onClose: () => void;
  onRemoved?: () => void;
}

/**
 * Confirms the deletion of a diagram.
 *
 * @param props Component props.
 * @returns The confirmation dialog.
 */
export function RemoveDiagramConfirm({
  open,
  modelId,
  diagramName,
  onClose,
  onRemoved,
}: RemoveDiagramConfirmProps) {
  const mutation = useRemoveDiagram(modelId, diagramName);
  return (
    <ConfirmDialog
      open={open}
      danger
      title={`Delete the ${diagramName} diagram?`}
      description="The diagram and the placement of its entities are removed. The entities themselves stay in the model."
      confirmLabel="Delete diagram"
      loading={mutation.isPending}
      onCancel={onClose}
      onConfirm={() => {
        mutation.mutate(undefined, {
          onSuccess: () => {
            onClose();
            onRemoved?.();
          },
        });
      }}
    />
  );
}
