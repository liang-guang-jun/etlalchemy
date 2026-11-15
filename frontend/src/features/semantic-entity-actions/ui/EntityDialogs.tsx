import { useEffect, useState } from 'react';

import type { Entity, EntityPatch } from '@/entities/semantic';
import { normalizeError } from '@/shared/api/error';
import { Button, ConfirmDialog, Dialog, Input } from '@/shared/ui';

import { useAddEntity, useChangeEntity, useRemoveEntity } from '../api/mutation';
import { TablePicker, type PickedTable } from './TablePicker';

const INVALID_NAME = 'Enter a name; it cannot be blank or contain “/”';

/**
 * Validates an entity name with the same rule as the aggregate.
 *
 * @param value Name to check.
 * @returns The error message, or `null` when the name is acceptable.
 */
function nameError(value: string): string | null {
  const trimmed = value.trim();
  if (trimmed === '' || trimmed.includes('/')) {
    return INVALID_NAME;
  }
  return null;
}

export interface CreateEntityDialogProps {
  open: boolean;
  modelId: string;
  onClose: () => void;
  onCreated?: (entityName: string) => void;
}

/**
 * Renders the entity creation form: a name and the catalog table it maps to.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function CreateEntityDialog({ open, modelId, onClose, onCreated }: CreateEntityDialogProps) {
  const mutation = useAddEntity(modelId);
  const [name, setName] = useState('');
  const [table, setTable] = useState<PickedTable | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setName('');
      setTable(null);
      setError(null);
    }
  }, [open]);

  return (
    <Dialog
      open={open}
      title="New entity"
      description="An entity is a business object backed by one catalog table."
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={mutation.isPending}
            onClick={() => {
              const invalid = nameError(name);
              if (invalid !== null) {
                setError(invalid);
                return;
              }
              if (table === null) {
                setError('Choose the catalog table the entity maps to');
                return;
              }
              setError(null);
              mutation.mutate(
                { name: name.trim(), table_id: table.id },
                {
                  onSuccess: () => {
                    onClose();
                    onCreated?.(name.trim());
                  },
                },
              );
            }}
          >
            Create
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <label className="block space-y-1">
          <span className="text-sm text-text">Name</span>
          <Input
            placeholder="Customer"
            value={name}
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
        </label>
        <div className="space-y-1">
          <span className="text-sm text-text">Catalog table</span>
          <TablePicker value={table} onChange={setTable} />
        </div>
        {error !== null ? <p className="text-sm text-danger">{error}</p> : null}
        {mutation.error !== null ? (
          <p className="text-sm text-danger">{normalizeError(mutation.error).detail}</p>
        ) : null}
      </div>
    </Dialog>
  );
}

export interface EditEntityDialogProps {
  open: boolean;
  modelId: string;
  entity: Entity;
  /** Whether a relationship references the entity, which locks the table. */
  inUse: boolean;
  onClose: () => void;
}

/**
 * Renames an entity and/or points it at another catalog table.
 *
 * Only the changed attributes are sent: the aggregate rejects a table change
 * while a relationship references the entity, even for the same table.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function EditEntityDialog({ open, modelId, entity, inUse, onClose }: EditEntityDialogProps) {
  const mutation = useChangeEntity(modelId, entity.name);
  const [name, setName] = useState(entity.name);
  const [table, setTable] = useState<PickedTable | null>({ id: entity.table_id });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setName(entity.name);
      // The label is resolved from the read model by the picker itself.
      setTable({ id: entity.table_id });
      setError(null);
    }
  }, [open, entity.name, entity.table_id]);

  return (
    <Dialog
      open={open}
      title="Edit entity"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={mutation.isPending}
            onClick={() => {
              const invalid = nameError(name);
              if (invalid !== null) {
                setError(invalid);
                return;
              }
              const body: EntityPatch = {};
              if (name.trim() !== entity.name) {
                body.new_name = name.trim();
              }
              if (table !== null && table.id !== entity.table_id) {
                body.table_id = table.id;
              }
              if (Object.keys(body).length === 0) {
                onClose();
                return;
              }
              setError(null);
              mutation.mutate(body, { onSuccess: onClose });
            }}
          >
            Save
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <label className="block space-y-1">
          <span className="text-sm text-text">Name</span>
          <Input
            value={name}
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
        </label>
        <div className="space-y-1">
          <span className="text-sm text-text">Catalog table</span>
          <TablePicker value={table} onChange={setTable} disabled={inUse} />
          {inUse ? (
            <p className="text-xs text-text-disabled">
              A relationship references this entity, so its table is locked. Delete the relationship
              first.
            </p>
          ) : null}
        </div>
        {error !== null ? <p className="text-sm text-danger">{error}</p> : null}
        {mutation.error !== null ? (
          <p className="text-sm text-danger">{normalizeError(mutation.error).detail}</p>
        ) : null}
      </div>
    </Dialog>
  );
}

export interface RemoveEntityConfirmProps {
  open: boolean;
  modelId: string;
  entityName: string;
  /** Number of relationships that are removed with the entity. */
  relationshipCount: number;
  onClose: () => void;
  onRemoved?: () => void;
}

/**
 * Confirms the cascade deletion of an entity.
 *
 * @param props Component props.
 * @returns The confirmation dialog.
 */
export function RemoveEntityConfirm({
  open,
  modelId,
  entityName,
  relationshipCount,
  onClose,
  onRemoved,
}: RemoveEntityConfirmProps) {
  const mutation = useRemoveEntity(modelId, entityName);
  return (
    <ConfirmDialog
      open={open}
      danger
      title={`Delete ${entityName}?`}
      description={
        relationshipCount === 0
          ? 'The entity is removed from every diagram of this model.'
          : `The entity is removed from every diagram together with ${relationshipCount} relationship(s).`
      }
      confirmLabel="Delete entity"
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
