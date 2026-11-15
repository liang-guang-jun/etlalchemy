import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { ArrowLeft, ChevronRight, GitBranch, Plus, Shapes } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { Link, useNavigate, useSearchParams } from 'react-router';

import {
  relationshipDetail,
  relationshipSummary,
  useEntities,
  useModel,
  useNodes,
  useRelationships,
  type Entity,
  type Relationship,
} from '@/entities/semantic';
import { usePlaceNode } from '@/features/semantic-diagram-actions';
import {
  CreateEntityDialog,
  EditEntityDialog,
  RemoveEntityConfirm,
} from '@/features/semantic-entity-actions';
import {
  RelationshipDialog,
  useRemoveRelationship,
} from '@/features/semantic-relationship-actions';
import {
  ALL_DIAGRAM,
  MODELS_PATH,
  parseWorkspaceSearch,
  workspacePath,
} from '@/shared/lib/semantic-routes';
import {
  ConfirmDialog,
  ErrorState,
  SearchInput,
  Skeleton,
  TreeMessage,
  TreeRow,
  type DropdownMenuItem,
} from '@/shared/ui';

/** Storage key of the section expansion state. */
const EXPANDED_KEY = 'semantic:explorerExpanded';

interface ExpandedState {
  entities: boolean;
  relationships: boolean;
}

const DEFAULT_EXPANDED: ExpandedState = { entities: true, relationships: true };

/**
 * Reads the persisted section state.
 *
 * @returns The expansion state, falling back to everything expanded.
 */
function readExpanded(): ExpandedState {
  const raw = window.localStorage.getItem(EXPANDED_KEY);
  if (raw === null) {
    return DEFAULT_EXPANDED;
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed === 'object' && parsed !== null) {
      const value = parsed as Partial<ExpandedState>;
      return {
        entities: value.entities !== false,
        relationships: value.relationships !== false,
      };
    }
  } catch {
    // A corrupted entry must not break the explorer.
  }
  return DEFAULT_EXPANDED;
}

interface SectionProps {
  title: string;
  count: number;
  expanded: boolean;
  onToggle: () => void;
  onCreate?: () => void;
  createLabel?: string;
  children: ReactNode;
}

/**
 * Renders one collapsible group of the explorer.
 *
 * @param props Component props.
 * @returns The section header and, while expanded, its rows.
 */
function Section({
  title,
  count,
  expanded,
  onToggle,
  onCreate,
  createLabel,
  children,
}: SectionProps) {
  return (
    <div className="select-none">
      <div className="group/section flex h-8 items-center gap-1 pl-1 pr-1">
        <button
          type="button"
          aria-expanded={expanded}
          onClick={onToggle}
          className="flex min-w-0 flex-1 items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-text-secondary transition-colors hover:text-text-primary"
        >
          <motion.span animate={{ rotate: expanded ? 90 : 0 }} className="flex">
            <ChevronRight className="size-3" aria-hidden="true" />
          </motion.span>
          <span className="truncate">{title}</span>
          <span className="font-normal text-text-disabled">{count}</span>
        </button>
        {onCreate === undefined ? null : (
          <button
            type="button"
            aria-label={createLabel ?? `Add to ${title}`}
            title={createLabel ?? `Add to ${title}`}
            onClick={onCreate}
            className="flex size-5 items-center justify-center text-text-disabled opacity-0 transition-all hover:text-text-primary group-hover/section:opacity-100"
          >
            <Plus className="size-3.5" aria-hidden="true" />
          </button>
        )}
      </div>
      <AnimatePresence initial={false}>
        {expanded ? (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.16, ease: 'easeOut' }}
            className="overflow-hidden"
          >
            {children}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

export interface SemanticExplorerProps {
  modelId: string;
}

/**
 * Renders the workspace explorer: the entities and relationships of one model,
 * filtered by a keyword box.
 *
 * The current diagram and the selected node live in the URL, so the explorer and
 * the canvas stay in sync without shared state.
 *
 * @param props Component props.
 * @returns The explorer panel.
 */
export function SemanticExplorer({ modelId }: SemanticExplorerProps) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const state = parseWorkspaceSearch(searchParams.toString());
  const diagramName = state.diagram ?? ALL_DIAGRAM;

  const model = useModel(modelId);
  const entities = useEntities(modelId);
  const relationships = useRelationships(modelId);
  const nodes = useNodes(modelId, diagramName);
  const place = usePlaceNode(modelId, diagramName);

  const [expanded, setExpanded] = useState<ExpandedState>(readExpanded);
  const [term, setTerm] = useState('');
  const [creatingEntity, setCreatingEntity] = useState(false);
  const [editingEntity, setEditingEntity] = useState<Entity | null>(null);
  const [removingEntity, setRemovingEntity] = useState<Entity | null>(null);
  const [creatingRelationship, setCreatingRelationship] = useState(false);
  const [editingRelationship, setEditingRelationship] = useState<Relationship | null>(null);
  const [removingRelationship, setRemovingRelationship] = useState<Relationship | null>(null);
  const removeRelationship = useRemoveRelationship(
    modelId,
    removingRelationship?.relationship_id ?? '',
  );

  useEffect(() => {
    window.localStorage.setItem(EXPANDED_KEY, JSON.stringify(expanded));
  }, [expanded]);

  const toggle = (key: keyof ExpandedState): void => {
    setExpanded((current) => ({ ...current, [key]: !current[key] }));
  };

  const entityRows = useMemo(() => entities.data ?? [], [entities.data]);
  const relationshipRows = useMemo(() => relationships.data ?? [], [relationships.data]);
  const placed = useMemo(
    () => new Set((nodes.data ?? []).map((node) => node.entity_name)),
    [nodes.data],
  );
  const referenced = useMemo(
    () =>
      new Set(
        relationshipRows.flatMap((row) => [
          ...row.from_refs.map((ref) => ref.entity),
          ...row.to_refs.map((ref) => ref.entity),
        ]),
      ),
    [relationshipRows],
  );

  const needle = term.trim().toLowerCase();
  const visibleEntities = useMemo(
    () =>
      needle === ''
        ? entityRows
        : entityRows.filter((entity) => entity.name.toLowerCase().includes(needle)),
    [entityRows, needle],
  );
  const visibleRelationships = useMemo(
    () =>
      needle === ''
        ? relationshipRows
        : relationshipRows.filter((relationship) =>
            `${relationshipSummary(relationship)} ${relationshipDetail(relationship)}`
              .toLowerCase()
              .includes(needle),
          ),
    [relationshipRows, needle],
  );

  /**
   * Builds the action menu of one entity.
   *
   * @param entity Entity the menu belongs to.
   * @returns The menu items.
   */
  const entityMenu = (entity: Entity): DropdownMenuItem[] => {
    const onDiagram = placed.has(entity.name);
    return [
      {
        label: onDiagram ? 'Reveal on the canvas' : 'Add to this diagram',
        disabled: onDiagram || diagramName === ALL_DIAGRAM,
        onSelect: () => {
          place.mutate({
            entity_name: entity.name,
            x: 80 + ((nodes.data?.length ?? 0) % 5) * 220,
            y: 60 + Math.floor((nodes.data?.length ?? 0) / 5) * 140,
          });
        },
      },
      {
        label: 'Edit entity',
        onSelect: () => {
          setEditingEntity(entity);
        },
      },
      {
        label: 'Delete entity',
        danger: true,
        onSelect: () => {
          setRemovingEntity(entity);
        },
      },
    ];
  };

  /**
   * Builds the action menu of one relationship.
   *
   * @param relationship Relationship the menu belongs to.
   * @returns The menu items.
   */
  const relationshipMenu = (relationship: Relationship): DropdownMenuItem[] => [
    {
      label: 'Edit relationship',
      onSelect: () => {
        setEditingRelationship(relationship);
      },
    },
    {
      label: 'Delete relationship',
      danger: true,
      onSelect: () => {
        setRemovingRelationship(relationship);
      },
    },
  ];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-11 shrink-0 items-center gap-2 border-b border-border-base px-2">
        <Link
          to={MODELS_PATH}
          aria-label="Back to models"
          title="Back to models"
          className="flex size-7 shrink-0 items-center justify-center rounded-sm text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
        >
          <ArrowLeft className="size-4" aria-hidden="true" />
        </Link>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-text-primary">
            {model.data?.name ?? 'Model'}
          </p>
          <p className="truncate text-[11px] text-text-secondary">Explorer</p>
        </div>
      </header>

      <div className="shrink-0 px-2 pb-2 pt-2">
        <SearchInput
          ariaLabel="Search entities and relationships"
          placeholder="Search entities and relationships…"
          value={term}
          onChange={setTerm}
        />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-1.5 pb-2">
        {entities.isPending ? (
          <Skeleton lines={8} />
        ) : entities.isError ? (
          <ErrorState
            detail={entities.error instanceof Error ? entities.error.message : undefined}
            onRetry={() => {
              void entities.refetch();
            }}
          />
        ) : (
          <div className="space-y-1">
            <Section
              title="Entities"
              count={visibleEntities.length}
              expanded={expanded.entities}
              onToggle={() => {
                toggle('entities');
              }}
              createLabel="New entity"
              onCreate={() => {
                setCreatingEntity(true);
              }}
            >
              {visibleEntities.length === 0 ? (
                <TreeMessage
                  depth={0}
                  text={entityRows.length === 0 ? 'No entity yet' : 'No match'}
                />
              ) : (
                visibleEntities.map((entity) => (
                  <TreeRow
                    key={entity.name}
                    depth={0}
                    label={entity.name}
                    icon={<Shapes className="size-3.5 text-text-secondary" aria-hidden="true" />}
                    to={workspacePath(modelId, { diagram: diagramName, entity: entity.name })}
                    active={state.entity === entity.name}
                    trailing={
                      placed.has(entity.name) ? (
                        <span
                          className="size-1.5 rounded-full bg-success"
                          title="On this diagram"
                        />
                      ) : null
                    }
                    menuItems={entityMenu(entity)}
                  />
                ))
              )}
            </Section>

            <Section
              title="Relationships"
              count={visibleRelationships.length}
              expanded={expanded.relationships}
              onToggle={() => {
                toggle('relationships');
              }}
              createLabel="New relationship"
              onCreate={() => {
                setCreatingRelationship(true);
              }}
            >
              {visibleRelationships.length === 0 ? (
                <TreeMessage
                  depth={0}
                  text={relationshipRows.length === 0 ? 'No relationship yet' : 'No match'}
                />
              ) : (
                visibleRelationships.map((relationship) => (
                  <TreeRow
                    key={relationship.relationship_id}
                    depth={0}
                    label={relationshipSummary(relationship)}
                    icon={<GitBranch className="size-3.5 text-text-secondary" aria-hidden="true" />}
                    to={workspacePath(modelId, {
                      diagram: diagramName,
                      relationship: relationship.relationship_id,
                    })}
                    active={state.relationship === relationship.relationship_id}
                    menuItems={relationshipMenu(relationship)}
                  />
                ))
              )}
            </Section>
          </div>
        )}
      </div>

      <p className="shrink-0 border-t border-border-base px-3 py-2 text-[11px] text-text-disabled">
        {placed.size} placed on {diagramName}
      </p>

      <CreateEntityDialog
        open={creatingEntity}
        modelId={modelId}
        onClose={() => {
          setCreatingEntity(false);
        }}
        onCreated={(name) => {
          void navigate(workspacePath(modelId, { diagram: diagramName, entity: name }));
        }}
      />

      {editingEntity !== null ? (
        <EditEntityDialog
          open
          modelId={modelId}
          entity={editingEntity}
          inUse={referenced.has(editingEntity.name)}
          onClose={() => {
            setEditingEntity(null);
          }}
        />
      ) : null}

      {removingEntity !== null ? (
        <RemoveEntityConfirm
          open
          modelId={modelId}
          entityName={removingEntity.name}
          relationshipCount={
            relationshipRows.filter((row) =>
              [...row.from_refs, ...row.to_refs].some((ref) => ref.entity === removingEntity.name),
            ).length
          }
          onClose={() => {
            setRemovingEntity(null);
          }}
          onRemoved={() => {
            if (state.entity === removingEntity.name) {
              void navigate(workspacePath(modelId, { diagram: diagramName }), { replace: true });
            }
          }}
        />
      ) : null}

      <RelationshipDialog
        open={creatingRelationship}
        modelId={modelId}
        entities={entityRows}
        onClose={() => {
          setCreatingRelationship(false);
        }}
      />

      {editingRelationship !== null ? (
        <RelationshipDialog
          open
          modelId={modelId}
          entities={entityRows}
          relationship={editingRelationship}
          onClose={() => {
            setEditingRelationship(null);
          }}
        />
      ) : null}

      {removingRelationship !== null ? (
        <ConfirmDialog
          open
          danger
          title="Delete this relationship?"
          description={`${relationshipSummary(removingRelationship)} is removed from the model.`}
          confirmLabel="Delete relationship"
          onCancel={() => {
            setRemovingRelationship(null);
          }}
          onConfirm={() => {
            removeRelationship.mutate(undefined, {
              onSuccess: () => {
                setRemovingRelationship(null);
              },
            });
          }}
        />
      ) : null}
    </div>
  );
}
