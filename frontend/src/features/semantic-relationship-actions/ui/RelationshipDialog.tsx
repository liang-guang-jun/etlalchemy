import { ArrowLeftRight, Search } from 'lucide-react';
import { motion } from 'motion/react';
import { useEffect, useMemo, useState } from 'react';

import { useTableFields } from '@/entities/field';
import {
  cardinalities,
  cardinalityNeedsReviewAfterSwap,
  clampPriority,
  filterDirections,
  INACTIVE_PRIORITY,
  isInactive,
  type Cardinality,
  type Entity,
  type FilterDirection,
  type Relationship,
  type RelationshipCreate,
} from '@/entities/semantic';
import { normalizeError } from '@/shared/api/error';
import { cn } from '@/shared/lib/cn';
import { Badge, Button, Dialog, Input, Select } from '@/shared/ui';

import { useAddRelationship, useChangeRelationship } from '../api/mutation';

/** One field pair of the draft, from side to to side. */
interface DraftPair {
  /** Field of the source entity. */
  fromField: string;
  /** Field of the target entity. */
  toField: string;
}

/** Labels of the cardinality values. */
const CARDINALITY_LABELS: Record<Cardinality, string> = {
  one_to_one: 'One to one (1:1)',
  one_to_many: 'One to many (1:N)',
  many_to_many: 'Many to many (N:N)',
};

/** Labels of the filter directions. */
const DIRECTION_LABELS: Record<FilterDirection, string> = {
  single: 'From → to',
  both: 'Both ways',
};

/** The side a field pick belongs to. */
type Side = 'from' | 'to';

interface FieldPaneProps {
  /** `From` or `To`, shown above the entity selector. */
  sideLabel: string;
  /** Accessible name of the entity selector. */
  entityLabel: string;
  entities: Entity[];
  entityName: string;
  onEntityChange: (name: string) => void;
  /** Field awaiting a counterpart, highlighted in the list. */
  pickedField: string;
  onFieldClick: (field: string) => void;
  /** Position of each mapped field, so the pane can number them. */
  mappedIndex: ReadonlyMap<string, number>;
}

/**
 * Shows the fields of one side as a searchable list.
 *
 * @param props Component props.
 * @returns The field pane.
 */
function FieldPane({
  sideLabel,
  entityLabel,
  entities,
  entityName,
  onEntityChange,
  pickedField,
  onFieldClick,
  mappedIndex,
}: FieldPaneProps) {
  const [query, setQuery] = useState('');
  const tableId = entities.find((entity) => entity.name === entityName)?.table_id ?? '';
  const fields = useTableFields(tableId);
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const rows = fields.data ?? [];
    return needle === ''
      ? rows
      : rows.filter(
          (field) =>
            field.name.toLowerCase().includes(needle) ||
            field.data_type.toLowerCase().includes(needle),
        );
  }, [fields.data, query]);

  return (
    <div className="flex min-w-0 flex-1 flex-col rounded-lg border border-border-base bg-bg-canvas">
      <div className="space-y-1.5 border-b border-border-base p-2">
        <span className="text-[10px] font-medium tracking-wide text-text-secondary uppercase">
          {sideLabel}
        </span>
        <Select
          aria-label={entityLabel}
          value={entityName}
          placeholder="Choose an entity"
          options={entities.map((entity) => ({ value: entity.name, label: entity.name }))}
          onChange={(event) => {
            onEntityChange(event.target.value);
          }}
        />
      </div>
      <div className="relative border-b border-border-base p-2">
        <Search
          className="pointer-events-none absolute top-1/2 left-4 size-3.5 -translate-y-1/2 text-text-secondary"
          aria-hidden="true"
        />
        <input
          type="search"
          aria-label={`Search ${sideLabel} fields`}
          placeholder="Search fields…"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
          }}
          className="h-8 w-full rounded-md border border-border-strong bg-bg-surface pr-2 pl-7 text-xs text-text-primary outline-none placeholder:text-text-disabled focus:border-brand"
        />
      </div>
      <div className="max-h-48 min-h-24 overflow-y-auto p-1">
        {entityName === '' ? (
          <p className="px-2 py-3 text-xs text-text-disabled">Pick an entity first.</p>
        ) : fields.isPending ? (
          <p className="px-2 py-3 text-xs text-text-disabled">Loading fields…</p>
        ) : visible.length === 0 ? (
          <p className="px-2 py-3 text-xs text-text-disabled">No field matches.</p>
        ) : (
          visible.map((field) => {
            const position = mappedIndex.get(field.name);
            const picked = field.name === pickedField;
            return (
              <button
                type="button"
                key={field.name}
                onClick={() => {
                  onFieldClick(field.name);
                }}
                aria-pressed={position !== undefined}
                title={
                  position === undefined
                    ? `Pair ${field.name}`
                    : `Unpair ${field.name} (pair ${String(position)})`
                }
                className={cn(
                  'flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-xs transition-colors',
                  picked ? 'bg-brand/25 text-text-primary' : 'hover:bg-brand/10',
                )}
              >
                <span
                  className={cn(
                    'grid size-4 shrink-0 place-items-center rounded-sm text-[10px] font-semibold',
                    position === undefined ? 'text-text-disabled' : 'bg-brand/30 text-text-primary',
                  )}
                >
                  {position ?? '·'}
                </span>
                <span className="min-w-0 flex-1 truncate font-mono text-text-primary">
                  {field.name}
                </span>
                <span className="shrink-0 text-[10px] text-text-disabled">{field.data_type}</span>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}

export interface RelationshipDialogProps {
  open: boolean;
  modelId: string;
  entities: Entity[];
  /** Relationship to edit; omit to create a new one. */
  relationship?: Relationship;
  onClose: () => void;
}

/**
 * Creates or edits a relationship in the two-column style of a BI model editor.
 *
 * Each side shows the fields of one entity; clicking a field on one side and
 * then one on the other adds a mapping. The swap button mirrors the whole
 * relationship — sides, mappings and, when the backend can express it, the
 * cardinality — while the two panes slide into each other's place. A priority of
 * `-1` marks the relationship as inactive and greys the editor out, because the
 * canvas then draws the edge dashed and leaves it out of filter propagation.
 *
 * @param props Component props.
 * @returns The dialog element.
 */
export function RelationshipDialog({
  open,
  modelId,
  entities,
  relationship,
  onClose,
}: RelationshipDialogProps) {
  const editing = relationship !== undefined;
  const create = useAddRelationship(modelId);
  const change = useChangeRelationship(modelId, relationship?.relationship_id ?? '');
  const mutation = editing ? change : create;

  const [fromEntity, setFromEntity] = useState('');
  const [toEntity, setToEntity] = useState('');
  const [pairs, setPairs] = useState<DraftPair[]>([]);
  const [cardinality, setCardinality] = useState<Cardinality>('one_to_many');
  const [direction, setDirection] = useState<FilterDirection>('single');
  const [priority, setPriority] = useState('0');
  const [picked, setPicked] = useState<{ side: Side; field: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    setError(null);
    setNote(null);
    setPicked(null);
    if (relationship === undefined) {
      setFromEntity('');
      setToEntity('');
      setPairs([]);
      setCardinality('one_to_many');
      setDirection('single');
      setPriority('0');
      return;
    }
    setFromEntity(relationship.from_refs[0]?.entity ?? '');
    setToEntity(relationship.to_refs[0]?.entity ?? '');
    setPairs(
      relationship.from_refs.map((from, index) => ({
        fromField: from.field,
        toField: relationship.to_refs[index]?.field ?? '',
      })),
    );
    setCardinality(
      (cardinalities as readonly string[]).includes(relationship.cardinality)
        ? (relationship.cardinality as Cardinality)
        : 'one_to_many',
    );
    setDirection(relationship.filter_direction === 'both' ? 'both' : 'single');
    setPriority(String(relationship.priority));
  }, [open, relationship]);

  const inactive = isInactive({ priority: clampPriority(priority) });

  const mappedBySide = useMemo(() => {
    const map = new Map<Side, Map<string, number>>([
      ['from', new Map<string, number>()],
      ['to', new Map<string, number>()],
    ]);
    pairs.forEach((pair, index) => {
      map.get('from')?.set(pair.fromField, map.get('from')?.get(pair.fromField) ?? index + 1);
      map.get('to')?.set(pair.toField, map.get('to')?.get(pair.toField) ?? index + 1);
    });
    return map;
  }, [pairs]);

  /**
   * Toggles a field of one pane.
   *
   * A field that already takes part in a pairing is unpaired again; otherwise
   * the click picks the field and the next click on the other side pairs the two.
   * Clicking the same side twice only moves the pick, so the fields can be
   * chosen in either order. The numbered markers next to the fields are the only
   * record of the pairings.
   *
   * @param side Side of the clicked pane.
   * @param field Field name that was clicked.
   */
  const pickField = (side: Side, field: string): void => {
    const paired = pairs.some((pair) =>
      side === 'from' ? pair.fromField === field : pair.toField === field,
    );
    if (paired) {
      setPairs((current) =>
        current.filter((pair) => (side === 'from' ? pair.fromField : pair.toField) !== field),
      );
      setPicked(null);
      return;
    }
    if (picked === null || picked.side === side) {
      setPicked({ side, field });
      return;
    }
    const fromField = side === 'from' ? field : picked.field;
    const toField = side === 'from' ? picked.field : field;
    setPicked(null);
    setPairs((current) =>
      current.some((pair) => pair.fromField === fromField && pair.toField === toField)
        ? current
        : [...current, { fromField, toField }],
    );
  };

  /**
   * Mirrors the relationship: both sides, every mapping and the panes.
   *
   * `one_to_many` has no `many_to_one` counterpart in the backend enum, so it
   * keeps its value and the editor asks the user to review it.
   */
  const swapSides = (): void => {
    setFromEntity(toEntity);
    setToEntity(fromEntity);
    setPairs((current) =>
      current.map((pair) => ({ fromField: pair.toField, toField: pair.fromField })),
    );
    setPicked(null);
    setNote(
      cardinalityNeedsReviewAfterSwap(cardinality)
        ? 'Sides swapped. Cardinality stays "One to many" because the backend has no "Many to one"; check it before saving.'
        : null,
    );
  };

  /**
   * Validates the draft and sends it to the backend.
   */
  const save = (): void => {
    if (fromEntity === '' || toEntity === '') {
      setError('Choose a source and a target entity');
      return;
    }
    if (pairs.length === 0) {
      setError('Add at least one field mapping');
      return;
    }
    if (pairs.some((pair) => pair.fromField === '' || pair.toField === '')) {
      setError('Fill both fields of every mapping');
      return;
    }
    const body: RelationshipCreate = {
      from_refs: pairs.map((pair) => ({ entity: fromEntity, field: pair.fromField })),
      to_refs: pairs.map((pair) => ({ entity: toEntity, field: pair.toField })),
      cardinality,
      filter_direction: direction,
      priority: clampPriority(priority),
    };
    setError(null);
    mutation.mutate(body, {
      onSuccess: () => {
        onClose();
      },
    });
  };

  const fromPane = { side: 'from' as const, sideLabel: 'From', entityName: fromEntity };
  const toPane = { side: 'to' as const, sideLabel: 'To', entityName: toEntity };

  /**
   * Renders one field pane, keyed by its entity.
   *
   * The key follows the entity rather than the side, so a swap makes the two
   * panes trade places with the `layout` animation instead of merely repainting
   * their content.
   *
   * @param pane Side description of the pane.
   * @returns The animated pane wrapper.
   */
  const renderPane = (pane: { side: Side; sideLabel: string; entityName: string }) => (
    <motion.div
      key={pane.entityName === '' ? `${pane.side}-empty` : pane.entityName}
      layout
      transition={{ duration: 0.3, ease: 'easeOut' }}
      className="flex min-w-0 flex-1"
    >
      <FieldPane
        sideLabel={pane.sideLabel}
        entityLabel={`${pane.sideLabel} entity`}
        entities={entities}
        entityName={pane.entityName}
        onEntityChange={(name) => {
          if (pane.side === 'from') {
            setFromEntity(name);
          } else {
            setToEntity(name);
          }
          setPicked(null);
        }}
        pickedField={picked?.side === pane.side ? picked.field : ''}
        onFieldClick={(field) => {
          pickField(pane.side, field);
        }}
        mappedIndex={mappedBySide.get(pane.side) ?? new Map<string, number>()}
      />
    </motion.div>
  );

  return (
    <Dialog
      open={open}
      size="lg"
      title={editing ? 'Edit relationship' : 'New relationship'}
      description="Click a field on one side, then one on the other to pair them; a second click on a paired field unpairs it."
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={mutation.isPending} onClick={save}>
            {editing ? 'Save' : 'Create'}
          </Button>
        </>
      }
    >
      <div className={cn('space-y-4 transition-opacity', inactive && 'opacity-90')}>
        <div className="flex items-stretch gap-2">
          {renderPane(fromPane)}
          <div className="flex flex-col justify-center">
            <Button
              variant="secondary"
              size="sm"
              aria-label="Swap from and to"
              title="Swap the two sides, their mappings and the cardinality"
              onClick={swapSides}
              className="h-8 w-8 px-0"
            >
              <ArrowLeftRight className="size-4" aria-hidden="true" />
            </Button>
          </div>
          {renderPane(toPane)}
        </div>

        {note !== null ? <p className="text-xs text-warning-ink">{note}</p> : null}

        <p className="text-xs text-text-secondary">
          {pairs.length === 0
            ? 'No field paired yet. Click a field on one side, then one on the other.'
            : `${String(pairs.length)} field ${pairs.length === 1 ? 'pair' : 'pairs'} — the numbered markers show them; click a paired field again to unpair it.`}
        </p>

        <div className="grid grid-cols-2 gap-3">
          <label className="block space-y-1">
            <span className="text-sm text-text">Cardinality</span>
            <Select
              value={cardinality}
              options={cardinalities.map((value) => ({
                value,
                label: CARDINALITY_LABELS[value],
              }))}
              onChange={(event) => {
                setCardinality(event.target.value as Cardinality);
              }}
            />
          </label>
          <label className="block space-y-1">
            <span className="text-sm text-text">Filter direction</span>
            <Select
              value={direction}
              options={filterDirections.map((value) => ({
                value,
                label: DIRECTION_LABELS[value],
              }))}
              onChange={(event) => {
                setDirection(event.target.value as FilterDirection);
              }}
            />
          </label>
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <label className="block w-28 space-y-1">
            <span className="text-sm text-text">Priority</span>
            <Input
              type="number"
              step={1}
              min={INACTIVE_PRIORITY}
              aria-label="Priority"
              value={priority}
              onChange={(event) => {
                setPriority(event.target.value);
              }}
              onBlur={() => {
                setPriority(String(clampPriority(priority)));
              }}
            />
          </label>
          <div className="flex items-center gap-1" role="group" aria-label="Priority presets">
            <Button
              size="sm"
              variant={inactive ? 'primary' : 'secondary'}
              aria-pressed={inactive}
              onClick={() => {
                setPriority(String(INACTIVE_PRIORITY));
              }}
            >
              Inactive (-1)
            </Button>
            <Button
              size="sm"
              variant={inactive ? 'secondary' : 'primary'}
              aria-pressed={!inactive}
              onClick={() => {
                setPriority('0');
              }}
            >
              Active (0)
            </Button>
          </div>
          <Badge tone={inactive ? 'neutral' : 'success'}>{inactive ? 'Inactive' : 'Active'}</Badge>
        </div>

        <div
          className={cn(
            'rounded-md border px-3 py-2 text-xs',
            inactive
              ? 'border-border-strong bg-bg-canvas text-text-secondary'
              : 'border-border-base bg-bg-canvas text-text-secondary',
          )}
        >
          {inactive
            ? 'Priority = -1: this relationship is inactive. The canvas draws it as a grey dashed line and it takes no part in filter propagation.'
            : 'Priority 0 or higher: the relationship is active and part of filter propagation.'}
        </div>

        {error !== null ? <p className="text-sm text-danger">{error}</p> : null}
        {mutation.error !== null ? (
          <p className="text-sm text-danger">{normalizeError(mutation.error).detail}</p>
        ) : null}
      </div>
    </Dialog>
  );
}
