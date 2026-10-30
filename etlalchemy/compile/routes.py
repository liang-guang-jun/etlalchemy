"""Turn the routes of a query into the relationships it traverses."""

from __future__ import annotations

from uuid import UUID

from etlalchemy.compile.context import CompileContext
from etlalchemy.compile.plan import referenced_entities
from etlalchemy.compile.resolve import ResolvedQuery, resolve_entity
from etlalchemy.semantic.expression import RouteKey
from etlalchemy.semantic.graph import GraphService
from etlalchemy.semantic.model import SemanticRegistry
from etlalchemy.semantic.relationship import SemanticRelationship
from etlalchemy.semantic.selection import edges_for_selection


def merged_routes(resolved: ResolvedQuery) -> dict[RouteKey, int]:
    """Merge the effective routes of every measure in the query.

    Raises:
        ValueError: If two measures require different priorities for one pair,
            because they would need different relationships and cannot share a
            single join.
    """
    merged: dict[RouteKey, int] = {}
    for measure in resolved.measures:
        for key, priority in measure.routes.items():
            existing = merged.get(key)
            if existing is not None and existing != priority:
                raise ValueError(
                    f"Conflicting routes for {key}: measures in one query must "
                    "agree on the relationship; split them into separate queries"
                )
            merged[key] = priority
    return merged


def _model_pairs(registry: SemanticRegistry) -> set[tuple[str, str]]:
    """Return every alias pair connected by a relationship, in both directions."""
    pairs: set[tuple[str, str]] = set()
    for relationship in registry.relationships:
        source = relationship.source_alias()
        target = relationship.target_alias()
        pairs.add((source, target))
        pairs.add((target, source))
    return pairs


def _validate_routes(
    merged: dict[RouteKey, int],
    resolved: ResolvedQuery,
    context: CompileContext,
) -> None:
    """Reject routes that name no relationship or no entity of the query.

    Raises:
        ValueError: If a pair has no relationship in the model, or if neither
            side of the pair is referenced by the query.
    """
    registry = context.model.registry
    known = set(registry.entities)
    known.update(entity.alias for entity in registry.entities.values())
    pairs = _model_pairs(registry)
    referenced = set(referenced_entities(resolved))
    for source, target in merged:
        if source not in known or target not in known or (source, target) not in pairs:
            raise ValueError(
                f"No relationship from {source!r} to {target!r} in the model"
            )
        if source not in referenced and target not in referenced:
            raise ValueError(
                f"Route pair ({source!r}, {target!r}) is not used by the query"
            )


def select_edges(
    resolved: ResolvedQuery,
    context: CompileContext,
) -> tuple[SemanticRelationship, ...]:
    """Select the active relationships of a query and reject cyclic selections.

    Args:
        resolved: Query whose references and routes are already resolved.
        context: Compilation state carrying the model.

    Returns:
        The relationships the query traverses.

    Raises:
        ValueError: If a route names an unknown or disconnected pair, or a
            pair the query does not use.
        RelationshipCycleError: If the selected edges contain a cycle.
    """
    registry = context.model.registry
    merged = merged_routes(resolved)
    _validate_routes(merged, resolved, context)

    selection: dict[tuple[UUID, UUID], int] = {}
    for (source, target), priority in merged.items():
        source_id = resolve_entity(source, context).id
        target_id = resolve_entity(target, context).id
        selection[(source_id, target_id)] = priority

    edges = edges_for_selection(registry, selection)
    known_entities = {entity.id: name for name, entity in registry.entities.items()}
    GraphService(edges, known_entities=known_entities).ensure_acyclic()
    return edges
