import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Background,
  BackgroundVariant,
  ControlButton,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  useNodesState,
  type Edge,
  type NodeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { LayoutGrid } from 'lucide-react';
import { useNavigate } from 'react-router';

import {
  cardinalityLabel,
  isInactive,
  useEntities,
  useNodes,
  useRelationships,
} from '@/entities/semantic';
import { useLayoutNodes, useMoveNode } from '@/features/semantic-diagram-actions';
import { isApiError } from '@/shared/api/error';
import { ALL_DIAGRAM, workspacePath } from '@/shared/lib/semantic-routes';
import { Button, EmptyState, ErrorState, Skeleton } from '@/shared/ui';

import { loadViewport, saveViewport } from '../model/viewport';
import type { EntityDetailLevel } from '../model/detail-level';
import { fieldsByEntity } from '../model/highlight';
import {
  alignToCenter,
  centerOf,
  FALLBACK_CARD_SIZE,
  layoutDiagram,
  overlappingPairs,
  type CardRect,
  type LayoutEdge,
  type LayoutPosition,
} from '../model/layout';
import { EntityNodeView, type EntityFlowNode } from './EntityNode';
import { NodeInspector } from './NodeInspector';

/** Custom node renderers, declared once so React Flow keeps its identity. */
const NODE_TYPES: NodeTypes = { entity: EntityNodeView };

/** Shared empty list, so the node-data patch can compare by reference. */
const NO_FIELDS: string[] = [];

/** Shared empty map, so an absent highlight keeps the same identity. */
const EMPTY_HIGHLIGHT = new Map<string, string[]>();

/**
 * Stacking level of the relationship under the pointer or the selection.
 *
 * Cards sit on the default level `0` and a selected card is raised to `1000`
 * by React Flow, so this lifts the edge above both without hiding the card the
 * inspector is showing.
 */
const ELEVATED_EDGE_Z_INDEX = 1_000;

/** A relationship edge; the smoothstep router takes the fan-out options. */
type RelationshipEdge = Edge<Record<string, unknown>, 'smoothstep'> & {
  pathOptions?: { borderRadius?: number; offset?: number };
};

/** Position of one card as it is written back to the model. */
interface LayoutRow {
  /** Entity name of the card. */
  entityName: string;
  /** Horizontal offset of the card. */
  x: number;
  /** Vertical offset of the card. */
  y: number;
}

/** How often the re-flow watcher compares the card sizes, in milliseconds. */
const REFLOW_CHECK_INTERVAL = 100;

/** Number of unchanged measurements that count as "the cards have settled". */
const REFLOW_STABLE_CHECKS = 2;

/** Shortest wait before a re-flow, so a quick switch never runs on a guess. */
const REFLOW_MIN_WAIT = 260;

/** How long the watcher keeps following the card sizes, in milliseconds. */
const REFLOW_WINDOW = 4_000;

/** How long an automatic layout waits for more movement before it is saved. */
const WRITE_DELAY = 1_500;

/**
 * Measures the cards from the rendered elements.
 *
 * The DOM is the source of truth: a card that is still animating its height, or
 * one that was just rebuilt from the read model, has no accurate measurement in
 * the node state, and the layout must not be computed from a guessed size.
 * `offsetWidth`/`offsetHeight` are the untransformed layout sizes, so the zoom
 * of the canvas does not influence them.
 *
 * @param root The canvas container.
 * @param nodes Cards of the canvas.
 * @returns One rectangle per card, in flow units.
 */
function measureCards(root: HTMLElement | null, nodes: readonly EntityFlowNode[]): CardRect[] {
  return nodes.map((node) => {
    const element = root?.querySelector<HTMLElement>(
      `.react-flow__node[data-id="${CSS.escape(node.id)}"]`,
    );
    const width = element?.offsetWidth || FALLBACK_CARD_SIZE.width;
    const height = element?.offsetHeight || FALLBACK_CARD_SIZE.height;
    return { id: node.id, x: node.position.x, y: node.position.y, width, height };
  });
}

export interface DiagramCanvasProps {
  modelId: string;
  diagramName: string;
  /** Entity selected in the URL, if any. */
  selectedEntity?: string;
  /** Relationship selected in the URL, if any. */
  selectedRelationship?: string;
  /** How much of each entity card is expanded. */
  detailLevel: EntityDetailLevel;
}

/**
 * Renders the entities of one diagram as a draggable graph.
 *
 * Node positions come from the read model; a drag updates the canvas locally and
 * saves `move_node` when the card is dropped, so the projection never makes a
 * card jump mid-drag. Edges are derived from the relationships whose two
 * entities are both placed on this diagram.
 *
 * @param props Component props.
 * @returns The canvas with its floating inspector.
 */
export function DiagramCanvas({
  modelId,
  diagramName,
  selectedEntity,
  selectedRelationship,
  detailLevel,
}: DiagramCanvasProps) {
  const navigate = useNavigate();
  const nodeRows = useNodes(modelId, diagramName);
  const entityRows = useEntities(modelId);
  const relationshipRows = useRelationships(modelId);
  const move = useMoveNode(modelId, diagramName);
  const layout = useLayoutNodes(modelId, diagramName);
  const [nodes, setNodes, onNodesChange] = useNodesState<EntityFlowNode>([]);
  const [hoveredRelationship, setHoveredRelationship] = useState<string | null>(null);
  const animationFrame = useRef<number | null>(null);
  const container = useRef<HTMLDivElement>(null);
  const saveTimer = useRef<number | null>(null);
  const pendingRows = useRef<LayoutRow[] | null>(null);

  useEffect(
    () => () => {
      if (animationFrame.current !== null) {
        window.cancelAnimationFrame(animationFrame.current);
      }
      if (saveTimer.current !== null) {
        window.clearTimeout(saveTimer.current);
      }
    },
    [],
  );

  const entities = useMemo(() => entityRows.data ?? [], [entityRows.data]);
  const relationships = useMemo(() => relationshipRows.data ?? [], [relationshipRows.data]);
  const cachedViewport = useMemo(() => loadViewport(modelId, diagramName), [modelId, diagramName]);

  const tableByEntity = useMemo(
    () => new Map(entities.map((entity) => [entity.name, entity.table_id])),
    [entities],
  );

  const relationFieldsByEntity = useMemo(() => {
    const fields = new Map<string, string[]>();
    for (const relationship of relationships) {
      for (const ref of [...relationship.from_refs, ...relationship.to_refs]) {
        const list = fields.get(ref.entity) ?? [];
        if (!list.includes(ref.field)) {
          list.push(ref.field);
        }
        fields.set(ref.entity, list);
      }
    }
    return fields;
  }, [relationships]);

  // The relationship under the pointer wins over the selected one, so pointing
  // at another edge previews its columns without losing the selection.
  const highlightId = hoveredRelationship ?? selectedRelationship;

  const hoveredInactive = useMemo(() => {
    const relationship = relationships.find((row) => row.relationship_id === hoveredRelationship);
    return relationship !== undefined && isInactive(relationship);
  }, [relationships, hoveredRelationship]);

  const highlightByEntity = useMemo(() => {
    const relationship = relationships.find((row) => row.relationship_id === highlightId);
    if (relationship === undefined) {
      return EMPTY_HIGHLIGHT;
    }
    return fieldsByEntity([...relationship.from_refs, ...relationship.to_refs]);
  }, [relationships, highlightId]);

  useEffect(() => {
    if (nodeRows.data === undefined) {
      return;
    }
    setNodes((current) => {
      // A card that is already on the canvas keeps its local position and its
      // measurement: the read model lags behind a write, so reading the projected
      // coordinates again would undo the layout or the drag that just happened.
      const previous = new Map(current.map((node) => [node.id, node]));
      return nodeRows.data.map((row) => {
        const existing = previous.get(row.entity_name);
        return {
          id: row.entity_name,
          type: 'entity',
          position: existing?.position ?? { x: row.x, y: row.y },
          measured: existing?.measured,
          data: {
            label: row.entity_name,
            tableId: tableByEntity.get(row.entity_name) ?? '',
            active: false,
            detailLevel: 'table' as const,
            relationFields: NO_FIELDS,
            highlightFields: NO_FIELDS,
            highlighted: false,
          },
        };
      });
    });
    // The highlight and the detail level are applied by the effects below, so
    // neither a selection nor a switch rebuilds the cards from possibly stale
    // coordinates.
  }, [nodeRows.data, tableByEntity, setNodes]);

  useEffect(() => {
    setNodes((current) => {
      let changed = false;
      const next = current.map((node) => {
        const relationFields = relationFieldsByEntity.get(node.id) ?? NO_FIELDS;
        const highlightFields = highlightByEntity.get(node.id) ?? NO_FIELDS;
        const highlighted = highlightByEntity.has(node.id);
        if (
          node.data.detailLevel === detailLevel &&
          node.data.relationFields === relationFields &&
          node.data.highlightFields === highlightFields &&
          node.data.highlighted === highlighted
        ) {
          return node;
        }
        changed = true;
        return {
          ...node,
          data: { ...node.data, detailLevel, relationFields, highlightFields, highlighted },
        };
      });
      return changed ? next : current;
    });
  }, [detailLevel, relationFieldsByEntity, highlightByEntity, nodeRows.data, setNodes]);

  useEffect(() => {
    setNodes((current) =>
      current.map((node) => {
        const active = node.id === selectedEntity;
        return node.data.active === active ? node : { ...node, data: { ...node.data, active } };
      }),
    );
  }, [selectedEntity, nodeRows.data, setNodes]);

  const placedNames = useMemo(() => new Set(nodes.map((node) => node.id)), [nodes]);

  /**
   * Entity pairs that have at least one reference between them.
   *
   * The layout only needs the shape of the graph, not the single field pairs,
   * so parallel references collapse into one entry.
   */
  const layoutEdges = useMemo<LayoutEdge[]>(() => {
    const seen = new Set<string>();
    const result: LayoutEdge[] = [];
    for (const relationship of relationships) {
      relationship.from_refs.forEach((from, index) => {
        const to = relationship.to_refs[index];
        if (to === undefined || !placedNames.has(from.entity) || !placedNames.has(to.entity)) {
          return;
        }
        const key = `${from.entity}->${to.entity}`;
        if (from.entity === to.entity || seen.has(key)) {
          return;
        }
        seen.add(key);
        result.push({ source: from.entity, target: to.entity });
      });
    }
    return result;
  }, [placedNames, relationships]);

  const edges = useMemo<RelationshipEdge[]>(() => {
    const result: RelationshipEdge[] = [];
    // Parallel references share the two centred handles of their cards, so each
    // further edge between the same pair turns out a little later: otherwise
    // their labels sit on exactly the same spot and read as one smudge.
    const fanOut = new Map<string, number>();
    for (const relationship of relationships) {
      relationship.from_refs.forEach((from, index) => {
        const to = relationship.to_refs[index];
        if (to === undefined || !placedNames.has(from.entity) || !placedNames.has(to.entity)) {
          return;
        }
        const pair = `${from.entity}->${to.entity}`;
        const parallel = fanOut.get(pair) ?? 0;
        fanOut.set(pair, parallel + 1);
        const selected = relationship.relationship_id === selectedRelationship;
        const hovered = relationship.relationship_id === hoveredRelationship;
        const emphasised = selected || hovered;
        // Priority -1 keeps the relationship but switches it off, which the
        // canvas shows as a grey dashed line.
        const inactive = isInactive(relationship);
        result.push({
          id: `${relationship.relationship_id}:${String(index)}`,
          source: from.entity,
          target: to.entity,
          type: 'smoothstep',
          pathOptions: { borderRadius: 16, offset: 18 + parallel * 16 },
          label: cardinalityLabel(relationship.cardinality),
          ariaLabel: `${cardinalityLabel(relationship.cardinality)} ${from.entity} to ${to.entity}${inactive ? ', inactive' : ''}`,
          // Both the hovered and the selected edge stay solid; only the width
          // separates the transient hover from the lasting selection.
          // Edges default to the z-index 0 layer below the cards; the one the
          // pointer or the selection is on is lifted so it crosses over them.
          zIndex: emphasised ? ELEVATED_EDGE_Z_INDEX : 0,
          markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
          style: {
            stroke: emphasised
              ? 'var(--color-brand-ink)'
              : inactive
                ? 'var(--color-text-disabled)'
                : 'var(--color-border-strong)',
            strokeWidth: selected ? 2.5 : hovered ? 2 : 1.5,
            strokeDasharray: inactive ? '6 4' : undefined,
            opacity: inactive && !emphasised ? 0.6 : 1,
          },
          labelBgStyle: { fill: 'var(--color-bg-surface)' },
          labelStyle: {
            fill: emphasised
              ? 'var(--color-brand-ink)'
              : inactive
                ? 'var(--color-text-disabled)'
                : 'var(--color-text-secondary)',
            fontSize: 11,
            fontWeight: emphasised ? 600 : 400,
          },
        });
      });
    }
    return result;
  }, [placedNames, relationships, selectedRelationship, hoveredRelationship]);

  const readOnlyDiagram = diagramName === ALL_DIAGRAM;

  /**
   * Saves the last automatic layout once the cards have stopped moving.
   *
   * One detail level change can re-flow more than once (the fields of the "all
   * columns" level arrive in a second step), so the write waits for the final
   * arrangement instead of storing every intermediate one.
   *
   * @param rows Final position of every card.
   */
  const saveLater = (rows: LayoutRow[]): void => {
    pendingRows.current = rows;
    if (saveTimer.current !== null) {
      window.clearTimeout(saveTimer.current);
    }
    saveTimer.current = window.setTimeout(() => {
      saveTimer.current = null;
      const pending = pendingRows.current;
      pendingRows.current = null;
      if (pending !== null) {
        layout.mutate(pending);
      }
    }, WRITE_DELAY);
  };

  /**
   * Slides every card to its target position frame by frame.
   *
   * The move is interpolated instead of using a CSS transition: React Flow owns
   * the `transform` of a node, so a transition would animate dragging too. The
   * serialised layout write runs once the cards have arrived.
   *
   * @param targets Target top-left corner per entity name.
   * @param persist Whether the new positions are saved right away or after the
   *   canvas has settled; an automatic re-flow uses the latter.
   */
  const animateTo = (targets: ReadonlyMap<string, LayoutPosition>, persist = true): void => {
    const origins = new Map(nodes.map((node) => [node.id, { ...node.position }]));
    const rows = nodes.flatMap((node) => {
      const target = targets.get(node.id);
      return target === undefined ? [] : [{ entityName: node.id, ...target }];
    });
    if (rows.length === 0) {
      return;
    }

    if (animationFrame.current !== null) {
      window.cancelAnimationFrame(animationFrame.current);
      animationFrame.current = null;
    }

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const duration = reduced ? 0 : 340;
    const startedAt = performance.now();

    const tick = (now: number): void => {
      const progress = duration === 0 ? 1 : Math.min(1, (now - startedAt) / duration);
      const eased = 1 - (1 - progress) ** 3;
      setNodes((current) =>
        current.map((node) => {
          const origin = origins.get(node.id);
          const target = targets.get(node.id);
          if (origin === undefined || target === undefined) {
            return node;
          }
          return {
            ...node,
            position: {
              x: origin.x + (target.x - origin.x) * eased,
              y: origin.y + (target.y - origin.y) * eased,
            },
          };
        }),
      );
      if (progress < 1) {
        animationFrame.current = window.requestAnimationFrame(tick);
        return;
      }
      animationFrame.current = null;
      if (persist) {
        layout.mutate(rows);
      } else {
        saveLater(rows);
      }
    };

    animationFrame.current = window.requestAnimationFrame(tick);
  };

  /**
   * Re-places the cards column by column with dagre and slides them there.
   *
   * Spacing follows the measured card height, so an entity expanded to all of
   * its columns keeps its distance to the card below it instead of covering it.
   * Relationships decide the column order, which keeps most edges pointing left
   * to right instead of looping back around their cards.
   *
   * @param persist Whether the result is saved right away; an automatic re-flow
   *   waits until the canvas has settled.
   */
  const autoLayout = (persist = true): void => {
    if (nodes.length === 0) {
      return;
    }
    const cards = measureCards(container.current, nodes);
    const sizes = new Map(
      cards.map((card) => [card.id, { width: card.width, height: card.height }]),
    );
    const laid = layoutDiagram(
      [...sizes].map(([id, size]) => ({ id, size })),
      layoutEdges,
    );
    const center = centerOf(cards);
    animateTo(center === null ? laid : alignToCenter(laid, sizes, center), persist);
  };

  // Published through refs so the polling effect below always works with the
  // latest closure, whatever the canvas rendered in the meantime.
  const autoLayoutRef = useRef(autoLayout);
  const nodesRef = useRef(nodes);
  useEffect(() => {
    autoLayoutRef.current = autoLayout;
    nodesRef.current = nodes;
  });

  // A new detail level resizes every card, so a grid tuned for the old size no
  // longer fits. The cards grow in an animation and, at the "all columns" level,
  // only once their fields have loaded, so the re-flow waits until the measured
  // sizes stop changing — and runs again if they settle at a different size.
  // Only a collision triggers it: a hand-arranged diagram that still fits keeps
  // its arrangement, and so does one whose cards became smaller.
  useEffect(() => {
    let lastSignature = '';
    let appliedSignature = '';
    let stableChecks = 0;
    let elapsed = 0;
    const timer = window.setInterval(() => {
      elapsed += REFLOW_CHECK_INTERVAL;
      const cards = measureCards(container.current, nodesRef.current);
      const signature = cards
        .map((card) => `${card.id}:${String(card.width)}x${String(card.height)}`)
        .join('|');
      stableChecks = signature === lastSignature ? stableChecks + 1 : 0;
      lastSignature = signature;
      if (
        stableChecks >= REFLOW_STABLE_CHECKS &&
        elapsed >= REFLOW_MIN_WAIT &&
        signature !== appliedSignature &&
        cards.length > 0
      ) {
        appliedSignature = signature;
        if (overlappingPairs(cards).length > 0) {
          autoLayoutRef.current(false);
        }
      }
      if (elapsed >= REFLOW_WINDOW) {
        window.clearInterval(timer);
      }
    }, REFLOW_CHECK_INTERVAL);
    return () => {
      window.clearInterval(timer);
    };
  }, [detailLevel]);

  return (
    <div ref={container} className="relative h-full w-full">
      {nodeRows.isPending ? (
        <div className="p-6">
          <Skeleton lines={5} />
        </div>
      ) : nodeRows.isError ? (
        <div className="p-6">
          {isApiError(nodeRows.error) && nodeRows.error.kind === 'not_found' ? (
            <EmptyState
              title="This diagram no longer exists"
              description={`“${diagramName}” was renamed or deleted. Open the All diagram to continue.`}
              action={
                <Button
                  variant="secondary"
                  onClick={() => {
                    void navigate(workspacePath(modelId, { diagram: ALL_DIAGRAM }), {
                      replace: true,
                    });
                  }}
                >
                  Open the All diagram
                </Button>
              }
              className="py-20"
            />
          ) : (
            <ErrorState
              detail={nodeRows.error instanceof Error ? nodeRows.error.message : undefined}
              onRetry={() => {
                void nodeRows.refetch();
              }}
            />
          )}
        </div>
      ) : (
        <ReactFlow
          key={diagramName}
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          onNodesChange={onNodesChange}
          onNodeDragStop={(_, node) => {
            move.mutate({
              entityName: node.id,
              body: { x: node.position.x, y: node.position.y },
            });
          }}
          onNodeClick={(_, node) => {
            void navigate(workspacePath(modelId, { diagram: diagramName, entity: node.id }));
          }}
          onEdgeClick={(_, edge) => {
            const relationshipId = edge.id.split(':')[0];
            if (relationshipId !== undefined) {
              void navigate(
                workspacePath(modelId, { diagram: diagramName, relationship: relationshipId }),
              );
            }
          }}
          onEdgeMouseEnter={(_, edge) => {
            setHoveredRelationship(edge.id.split(':')[0] ?? null);
          }}
          onEdgeMouseLeave={() => {
            setHoveredRelationship(null);
          }}
          onPaneClick={() => {
            if (selectedEntity !== undefined || selectedRelationship !== undefined) {
              void navigate(workspacePath(modelId, { diagram: diagramName }), { replace: true });
            }
          }}
          onMoveEnd={(_, viewport) => {
            saveViewport(modelId, diagramName, viewport);
          }}
          defaultViewport={cachedViewport ?? undefined}
          fitView={cachedViewport === null}
          fitViewOptions={{ padding: 0.25, maxZoom: 1 }}
          minZoom={0.2}
          maxZoom={2}
          nodesConnectable={false}
          elementsSelectable={false}
          attributionPosition="top-right"
          className="bg-bg-canvas"
        >
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
          <Controls position="bottom-left" showInteractive={false}>
            <ControlButton
              onClick={() => {
                autoLayout();
              }}
              disabled={nodes.length === 0}
              aria-label="Auto layout"
              title="Arrange the cards column by column, then drag them to fine-tune"
            >
              <LayoutGrid className="size-3.5" aria-hidden="true" />
            </ControlButton>
          </Controls>
          <MiniMap
            pannable
            zoomable
            className="!rounded-md border border-border-base shadow-sm"
            style={{
              backgroundColor: 'var(--color-bg-surface)',
              width: 168,
              height: 112,
            }}
            maskColor="rgb(37 36 35 / 0.08)"
            nodeColor="var(--color-brand)"
            nodeStrokeColor="var(--color-border-strong)"
            nodeBorderRadius={3}
          />
        </ReactFlow>
      )}

      {hoveredInactive ? (
        <div className="pointer-events-none absolute bottom-4 left-1/2 z-10 -translate-x-1/2 rounded-md border border-border-strong bg-bg-surface px-3 py-1.5 text-xs text-text-secondary shadow-sm">
          Inactive relationship (priority −1) · not part of filter propagation
        </div>
      ) : null}

      {!nodeRows.isPending && !nodeRows.isError && nodes.length === 0 ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <EmptyState
            plain
            title={readOnlyDiagram ? 'No entity yet' : 'This diagram is empty'}
            description={
              readOnlyDiagram
                ? 'Add an entity to the model; the All diagram shows every one of them.'
                : 'Add an entity from the explorer, then place it on this diagram.'
            }
            className="max-w-sm"
          />
        </div>
      ) : null}

      <NodeInspector
        modelId={modelId}
        diagramName={diagramName}
        readOnlyDiagram={readOnlyDiagram}
        entities={entities}
        relationships={relationships}
        selectedEntity={selectedEntity}
        selectedRelationship={selectedRelationship}
        placed={selectedEntity !== undefined && placedNames.has(selectedEntity)}
      />
    </div>
  );
}
