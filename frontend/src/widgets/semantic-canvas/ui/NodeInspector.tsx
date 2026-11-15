import { ArrowDown, Copy, ExternalLink, Pencil, Trash2, X } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router';

import {
  cardinalities,
  cardinalityLabel,
  clampPriority,
  filterDirections,
  INACTIVE_PRIORITY,
  isInactive,
  relationshipDetail,
  relationshipSummary,
  useModel,
  type Cardinality,
  type Entity,
  type FilterDirection,
  type Relationship,
} from '@/entities/semantic';
import { useTableLocation } from '@/entities/table';
import { CommentPanelBody } from '@/features/comment-threads';
import { usePlaceNode, useRemoveNode } from '@/features/semantic-diagram-actions';
import { EditEntityDialog, RemoveEntityConfirm } from '@/features/semantic-entity-actions';
import {
  RelationshipDialog,
  useChangeRelationship,
  useRemoveRelationship,
} from '@/features/semantic-relationship-actions';
import { cn } from '@/shared/lib/cn';
import { tablePath } from '@/shared/lib/catalog-routes';
import { workspacePath } from '@/shared/lib/semantic-routes';
import { Badge, Button, ConfirmDialog, Input, Select, Tabs, toast } from '@/shared/ui';

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

/** How long the priority input waits for more typing before it saves. */
const PRIORITY_SAVE_DELAY = 600;

export interface NodeInspectorProps {
  modelId: string;
  diagramName: string;
  /** Whether the current diagram is the built-in `All` diagram. */
  readOnlyDiagram: boolean;
  entities: Entity[];
  relationships: Relationship[];
  selectedEntity?: string;
  selectedRelationship?: string;
  /** Whether the selected entity is placed on the current diagram. */
  placed: boolean;
}

/**
 * Renders the properties of the selected entity or relationship over the canvas.
 *
 * The panel is a property inspector, not a detail page: the facts that can be
 * expressed as a control (priority, cardinality, filter direction) are edited in
 * place and saved right away, the relationships of an entity are listed as
 * links that select the edge on the canvas, and only the multi-column field
 * mapping still lives in a dialog. The panel is an overlay so the canvas keeps
 * its full width.
 *
 * @param props Component props.
 * @returns The floating panel, or nothing when no node is selected.
 */
export function NodeInspector({
  modelId,
  diagramName,
  readOnlyDiagram,
  entities,
  relationships,
  selectedEntity,
  selectedRelationship,
  placed,
}: NodeInspectorProps) {
  const navigate = useNavigate();
  const place = usePlaceNode(modelId, diagramName);
  const removeNode = useRemoveNode(modelId, diagramName);
  const relationship = relationships.find((row) => row.relationship_id === selectedRelationship);
  const change = useChangeRelationship(modelId, relationship?.relationship_id ?? '', {
    notify: false,
  });
  const removeRelationship = useRemoveRelationship(modelId, relationship?.relationship_id ?? '');
  const entity = entities.find((row) => row.name === selectedEntity);
  const model = useModel(modelId);
  const [tab, setTab] = useState<'properties' | 'discussion'>('properties');
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [editingRelationship, setEditingRelationship] = useState(false);
  const [deletingRelationship, setDeletingRelationship] = useState(false);

  // The controls keep their own copy of the value they edit, so a click or a
  // keystroke shows up immediately while the request is still in flight.
  const [priority, setPriority] = useState('0');
  const [cardinality, setCardinality] = useState<Cardinality>('one_to_many');
  const [direction, setDirection] = useState<FilterDirection>('single');
  const saveTimer = useRef<number | null>(null);

  useEffect(() => {
    if (relationship === undefined) {
      return;
    }
    setPriority(String(relationship.priority));
    setCardinality(
      (cardinalities as readonly string[]).includes(relationship.cardinality)
        ? (relationship.cardinality as Cardinality)
        : 'one_to_many',
    );
    setDirection(relationship.filter_direction === 'both' ? 'both' : 'single');
  }, [relationship]);

  useEffect(
    () => () => {
      if (saveTimer.current !== null) {
        window.clearTimeout(saveTimer.current);
      }
    },
    [],
  );

  const open = entity !== undefined || relationship !== undefined;
  const inactive = clampPriority(priority) === INACTIVE_PRIORITY;

  // Entities and relationships carry their own identity now, so each one is
  // discussed on its own; the link carries the current diagram with it.
  const discussionTarget =
    entity === undefined
      ? relationship === undefined
        ? null
        : {
            type: 'relationship' as const,
            id: relationship.relationship_id,
            label: relationshipSummary(relationship),
            href: workspacePath(modelId, {
              diagram: diagramName,
              relationship: relationship.relationship_id,
            }),
          }
      : entity.entity_id === null || entity.entity_id === undefined
        ? {
            type: 'semantic_model' as const,
            id: modelId,
            label: model.data?.name ?? 'this model',
            href: workspacePath(modelId, { diagram: diagramName }),
          }
        : {
            type: 'semantic_entity' as const,
            id: entity.entity_id,
            label: entity.name,
            href: workspacePath(modelId, { diagram: diagramName, entity: entity.name }),
          };

  // Switching selection returns to the properties of the new node.
  useEffect(() => {
    setTab('properties');
  }, [selectedEntity, selectedRelationship]);

  const close = (): void => {
    void navigate(workspacePath(modelId, { diagram: diagramName }), { replace: true });
  };

  useEffect(() => {
    if (!open) {
      return undefined;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        void navigate(workspacePath(modelId, { diagram: diagramName }), { replace: true });
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [open, modelId, diagramName, navigate]);

  const entityRelationships =
    entity === undefined
      ? []
      : relationships.filter((row) =>
          [...row.from_refs, ...row.to_refs].some((ref) => ref.entity === entity.name),
        );

  /**
   * Saves the priority that is currently typed.
   *
   * @param value Priority to send.
   */
  const commitPriority = (value: number): void => {
    if (relationship !== undefined && value !== relationship.priority) {
      change.mutate({ priority: value });
    }
  };

  /**
   * Stores the typed priority and schedules the save.
   *
   * @param raw Value of the input.
   */
  const draftPriority = (raw: string): void => {
    setPriority(raw);
    if (saveTimer.current !== null) {
      window.clearTimeout(saveTimer.current);
    }
    saveTimer.current = window.setTimeout(() => {
      saveTimer.current = null;
      commitPriority(clampPriority(raw));
    }, PRIORITY_SAVE_DELAY);
  };

  /** Saves a pending priority edit right away and normalises the input. */
  const flushPriority = (): void => {
    const value = clampPriority(priority);
    setPriority(String(value));
    if (saveTimer.current !== null) {
      window.clearTimeout(saveTimer.current);
      saveTimer.current = null;
    }
    commitPriority(value);
  };

  return (
    <>
      <AnimatePresence>
        {open ? (
          <motion.aside
            key="inspector"
            initial={{ opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 24 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className="absolute top-3 right-3 bottom-3 z-10 flex w-80 flex-col overflow-hidden rounded-lg border border-border-base bg-bg-surface shadow-md"
            aria-label="Inspector"
          >
            <header className="flex shrink-0 items-start justify-between gap-2 border-b border-border-base px-3 py-2">
              <div className="min-w-0">
                <p className="flex min-w-0 items-center gap-1.5 text-sm font-semibold text-text-primary">
                  <span className="truncate">
                    {entity?.name ?? (relationship ? relationshipSummary(relationship) : '')}
                  </span>
                  {entity !== undefined ? (
                    <button
                      type="button"
                      aria-label="Edit entity"
                      title="Edit entity"
                      onClick={() => {
                        setEditing(true);
                      }}
                      className="shrink-0 rounded-sm p-1 text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
                    >
                      <Pencil className="size-3.5" aria-hidden="true" />
                    </button>
                  ) : null}
                </p>
                <p className="mt-0.5 text-[10px] tracking-wide text-text-secondary uppercase">
                  {entity !== undefined ? 'Entity' : 'Relationship'}
                  {relationship !== undefined && change.isPending ? ' · saving…' : ''}
                </p>
              </div>
              <button
                type="button"
                aria-label="Close inspector"
                onClick={close}
                className="flex size-6 shrink-0 items-center justify-center rounded-sm text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
              >
                <X className="size-4" aria-hidden="true" />
              </button>
            </header>

            <Tabs
              className="shrink-0 px-3 pt-1"
              items={[
                { value: 'properties', label: 'Properties' },
                { value: 'discussion', label: 'Discussion' },
              ]}
              value={tab}
              onChange={(value) => {
                setTab(value === 'discussion' ? 'discussion' : 'properties');
              }}
            />

            {tab === 'discussion' && discussionTarget !== null ? (
              <div className="min-h-0 flex-1 overflow-hidden p-3">
                <CommentPanelBody target={discussionTarget} />
              </div>
            ) : (
              <>
                <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3 text-sm">
                  {entity !== undefined ? (
                    <>
                      <Section label="Catalog table">
                        <TableUri tableId={entity.table_id} />
                      </Section>

                      <Section label={`Relationships (${String(entityRelationships.length)})`}>
                        {entityRelationships.length === 0 ? (
                          <p className="text-xs text-text-disabled">
                            No relationship uses this entity.
                          </p>
                        ) : (
                          <ul className="space-y-1">
                            {entityRelationships.map((row) => (
                              <li key={row.relationship_id}>
                                <button
                                  type="button"
                                  onClick={() => {
                                    void navigate(
                                      workspacePath(modelId, {
                                        diagram: diagramName,
                                        relationship: row.relationship_id,
                                      }),
                                    );
                                  }}
                                  className={cn(
                                    'flex w-full items-center gap-2 rounded-md border px-2 py-1.5 text-left text-xs transition-colors',
                                    isInactive(row)
                                      ? 'border-dashed border-border-strong text-text-secondary'
                                      : 'border-border-base text-text-primary hover:border-brand hover:bg-brand/10',
                                  )}
                                >
                                  <span className="min-w-0 flex-1 truncate">
                                    {relationshipSummary(row)}
                                  </span>
                                  <Badge tone="neutral">{cardinalityLabel(row.cardinality)}</Badge>
                                </button>
                              </li>
                            ))}
                          </ul>
                        )}
                      </Section>
                    </>
                  ) : relationship !== undefined ? (
                    <>
                      <Section label="Status">
                        <div
                          className={cn(
                            'rounded-md border px-2 py-1.5',
                            inactive
                              ? 'border-border-strong bg-bg-canvas'
                              : 'border-success/30 bg-success/10',
                          )}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="flex items-center gap-1.5 text-xs text-text-primary">
                              <span
                                aria-hidden="true"
                                className={cn(
                                  'size-1.5 rounded-full',
                                  inactive ? 'bg-text-disabled' : 'bg-success',
                                )}
                              />
                              {inactive ? 'Inactive' : 'Active'}
                            </span>
                            <label className="flex items-center gap-1.5">
                              <span className="text-[10px] text-text-secondary">Priority</span>
                              <Input
                                type="number"
                                step={1}
                                min={INACTIVE_PRIORITY}
                                aria-label="Priority"
                                value={priority}
                                onChange={(event) => {
                                  draftPriority(event.target.value);
                                }}
                                onBlur={flushPriority}
                                onKeyDown={(event) => {
                                  if (event.key === 'Enter') {
                                    flushPriority();
                                  }
                                }}
                                className="h-7 w-20 px-2 text-xs"
                              />
                            </label>
                          </div>
                          <p className="mt-1 text-[10px] text-text-secondary">
                            {inactive
                              ? 'Priority -1: the canvas draws this edge dashed and grey; it takes no part in filter propagation.'
                              : 'Enter -1 to deactivate the relationship.'}
                          </p>
                        </div>
                      </Section>

                      <Section label="Fields">
                        <div className="space-y-1.5">
                          {relationship.from_refs.map((from, index) => {
                            const to = relationship.to_refs[index];
                            return (
                              <div
                                key={`${from.entity}.${from.field}`}
                                className="rounded-md border border-border-base bg-bg-canvas px-2 py-1.5 text-xs"
                              >
                                <p className="truncate">
                                  <span className="text-text-secondary">{from.entity}.</span>
                                  <span className="font-mono text-text-primary">{from.field}</span>
                                </p>
                                <ArrowDown
                                  className="my-0.5 size-3 text-text-disabled"
                                  aria-hidden="true"
                                />
                                <p className="truncate">
                                  <span className="text-text-secondary">{to?.entity ?? '—'}.</span>
                                  <span className="font-mono text-text-primary">
                                    {to?.field ?? ''}
                                  </span>
                                </p>
                              </div>
                            );
                          })}
                        </div>
                        <Button
                          variant="secondary"
                          size="sm"
                          icon={<Pencil className="size-3.5" />}
                          onClick={() => {
                            setEditingRelationship(true);
                          }}
                          className="mt-1.5"
                        >
                          Edit fields…
                        </Button>
                      </Section>

                      <Section label="Cardinality">
                        <Select
                          aria-label="Cardinality"
                          value={cardinality}
                          options={cardinalities.map((value) => ({
                            value,
                            label: CARDINALITY_LABELS[value],
                          }))}
                          onChange={(event) => {
                            const value = event.target.value as Cardinality;
                            setCardinality(value);
                            change.mutate({ cardinality: value });
                          }}
                          className="h-8 text-xs"
                        />
                      </Section>

                      <Section label="Filter direction">
                        <Select
                          aria-label="Filter direction"
                          value={direction}
                          options={filterDirections.map((value) => ({
                            value,
                            label: DIRECTION_LABELS[value],
                          }))}
                          onChange={(event) => {
                            const value = event.target.value as FilterDirection;
                            setDirection(value);
                            change.mutate({ filter_direction: value });
                          }}
                          className="h-8 text-xs"
                        />
                      </Section>
                    </>
                  ) : null}
                </div>

                <footer className="flex shrink-0 flex-wrap gap-2 border-t border-border-base p-3">
                  {entity !== undefined ? (
                    <>
                      {readOnlyDiagram ? null : placed ? (
                        <Button
                          variant="secondary"
                          size="sm"
                          loading={removeNode.isPending}
                          onClick={() => {
                            removeNode.mutate(entity.name, { onSuccess: close });
                          }}
                        >
                          Remove from diagram
                        </Button>
                      ) : (
                        <Button
                          variant="secondary"
                          size="sm"
                          loading={place.isPending}
                          onClick={() => {
                            place.mutate({ entity_name: entity.name, x: 120, y: 120 });
                          }}
                        >
                          Add to this diagram
                        </Button>
                      )}
                      <Button
                        variant="danger-ghost"
                        size="sm"
                        icon={<Trash2 className="size-3.5" />}
                        onClick={() => {
                          setDeleting(true);
                        }}
                      >
                        Delete
                      </Button>
                    </>
                  ) : relationship !== undefined ? (
                    <Button
                      variant="danger-ghost"
                      size="sm"
                      icon={<Trash2 className="size-3.5" />}
                      onClick={() => {
                        setDeletingRelationship(true);
                      }}
                    >
                      Delete
                    </Button>
                  ) : null}
                </footer>
              </>
            )}
          </motion.aside>
        ) : null}
      </AnimatePresence>

      {entity !== undefined ? (
        <>
          <EditEntityDialog
            open={editing}
            modelId={modelId}
            entity={entity}
            inUse={entityRelationships.length > 0}
            onClose={() => {
              setEditing(false);
            }}
          />
          <RemoveEntityConfirm
            open={deleting}
            modelId={modelId}
            entityName={entity.name}
            relationshipCount={entityRelationships.length}
            onClose={() => {
              setDeleting(false);
            }}
            onRemoved={close}
          />
        </>
      ) : null}

      {relationship !== undefined ? (
        <>
          <RelationshipDialog
            open={editingRelationship}
            modelId={modelId}
            entities={entities}
            relationship={relationship}
            onClose={() => {
              setEditingRelationship(false);
            }}
          />
          <ConfirmDialog
            open={deletingRelationship}
            danger
            title="Delete this relationship?"
            description={`${relationshipDetail(relationship)} is removed from the model.`}
            confirmLabel="Delete relationship"
            loading={removeRelationship.isPending}
            onCancel={() => {
              setDeletingRelationship(false);
            }}
            onConfirm={() => {
              removeRelationship.mutate(undefined, {
                onSuccess: () => {
                  setDeletingRelationship(false);
                  close();
                },
              });
            }}
          />
        </>
      ) : null}
    </>
  );
}

interface SectionProps {
  label: string;
  children: ReactNode;
}

/**
 * Renders one labelled block of the inspector.
 *
 * @param props Component props.
 * @returns The section.
 */
function Section({ label, children }: SectionProps) {
  return (
    <section className="space-y-1.5">
      <h3 className="text-[10px] font-medium tracking-wide text-text-secondary uppercase">
        {label}
      </h3>
      {children}
    </section>
  );
}

/**
 * Renders the `schema.table` path of a catalog table, linked to its detail page.
 *
 * The raw table id stays out of the way: it is only copied on demand.
 *
 * @param props Component props.
 * @returns The link, with a copy button next to it.
 */
function TableUri({ tableId }: { tableId: string }) {
  const location = useTableLocation(tableId);
  const table = location.data;

  if (table === undefined) {
    return <span className="font-mono text-xs text-text-disabled">{tableId.slice(0, 8)}…</span>;
  }

  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <a
        href={tablePath(table.catalog_id, table.schema_name, table.name)}
        target="_blank"
        rel="noreferrer"
        title={`Open ${table.schema_name}.${table.name} in the catalog`}
        className="inline-flex min-w-0 items-center gap-1 font-mono text-xs text-text-primary underline-offset-2 hover:text-brand-ink hover:underline"
      >
        <span className="truncate">
          {table.schema_name}.{table.name}
        </span>
        <ExternalLink className="size-3 shrink-0 text-text-disabled" aria-hidden="true" />
      </a>
      <button
        type="button"
        aria-label="Copy table id"
        title="Copy table id"
        onClick={() => {
          void navigator.clipboard
            .writeText(tableId)
            .then(() => {
              toast.success('Table id copied');
            })
            .catch(() => {
              toast.error('Could not copy the table id');
            });
        }}
        className="shrink-0 rounded-sm p-1 text-text-disabled transition-colors hover:bg-bg-hover hover:text-text-primary"
      >
        <Copy className="size-3" aria-hidden="true" />
      </button>
    </div>
  );
}
