"""Edge selections over the local priority groups of a registry.

Priority is a local selection group: every ``(source entity, target entity)``
pair may hold several relationships with different priorities, and at runtime
each pair independently elects one effective relationship. Pairs do not
influence each other, so there is no global priority layer and the full set of
combinations cannot be enumerated in advance. The helpers below produce the
edge sets a ``GraphService`` can analyse:

* :func:`all_edges` — every edge, for a worst-case check: if this set is
  acyclic no selection can be cyclic, and if it is cyclic some selection is.
* :func:`highest_priority_edges` — the default selection.
* :func:`lowest_priority_edges` — the opposite extreme, useful for diagnosis.
* :func:`edges_for_selection` — an explicit priority choice per pair.
* :func:`edges_by_priority` — one priority level at a time, for checking that
  each level is self-consistent. This is not a substitute for the runtime
  graph, which may mix priorities across pairs.

All helpers return tuples sorted by ``(source id, target id, priority, name)``
so results are immutable and directly comparable.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from uuid import UUID

from etlalchemy.semantic.model import SemanticRegistry
from etlalchemy.semantic.relationship import SemanticRelationship

#: Key of one local selection group: ``(source entity id, target entity id)``.
EntityIdPair = tuple[UUID, UUID]


def _entity_id(
    registry: SemanticRegistry,
    alias: str,
    relationship: SemanticRelationship,
) -> UUID:
    """Return the id of the entity registered under an alias.

    Raises:
        ValueError: If no registered entity uses the alias.
    """
    entity = registry.entities.get(alias)
    if entity is None:
        entity = next(
            (item for item in registry.entities.values() if item.alias == alias),
            None,
        )
    if entity is None:
        raise ValueError(
            f"Unknown entity alias {alias!r} in relationship {relationship.name!r}"
        )
    return entity.id


def _pair(
    relationship: SemanticRelationship, registry: SemanticRegistry
) -> EntityIdPair:
    """Return the selection group an edge belongs to."""
    return (
        _entity_id(registry, relationship.source_alias(), relationship),
        _entity_id(registry, relationship.target_alias(), relationship),
    )


def _sort_key(
    relationship: SemanticRelationship, registry: SemanticRegistry
) -> tuple[UUID, UUID, int, str]:
    """Return a deterministic ordering key for a relationship."""
    return (*_pair(relationship, registry), relationship.priority, relationship.name)


def _ordered(
    relationships: Iterable[SemanticRelationship],
    registry: SemanticRegistry,
) -> tuple[SemanticRelationship, ...]:
    """Return the relationships as a deterministically ordered tuple."""
    return tuple(sorted(relationships, key=lambda item: _sort_key(item, registry)))


def _grouped(
    registry: SemanticRegistry,
) -> dict[EntityIdPair, list[SemanticRelationship]]:
    """Group the registry relationships by their selection pair."""
    groups: dict[EntityIdPair, list[SemanticRelationship]] = {}
    for relationship in registry.relationships:
        groups.setdefault(_pair(relationship, registry), []).append(relationship)
    return groups


def _preference_key(
    relationship: SemanticRelationship, *, highest: bool
) -> tuple[int, str]:
    """Return the ordering key that ranks the preferred edge first."""
    priority = -relationship.priority if highest else relationship.priority
    return (priority, relationship.name)


def _preferred(
    candidates: Iterable[SemanticRelationship], *, highest: bool
) -> SemanticRelationship:
    """Return the highest or lowest priority edge of one node pair.

    Ties on priority are always broken by taking the smallest relationship
    name, so ``highest`` and ``lowest`` stay consistent: ``highest`` orders by
    descending priority then ascending name, ``lowest`` by ascending priority
    then ascending name.
    """
    return min(candidates, key=lambda item: _preference_key(item, highest=highest))


def all_edges(registry: SemanticRegistry) -> tuple[SemanticRelationship, ...]:
    """Return every relationship in the registry, ignoring priority.

    This is the worst-case edge set. ``GraphService.find_cycles`` only
    enumerates simple cycles, and a simple cycle never visits the same node
    pair twice. Every cycle found in this full edge set therefore uses at most
    one edge per ``(source entity, target entity)`` pair, which is exactly one
    legal "choose one edge per pair" selection. Consequently:

    * a cyclic result proves that some per-pair selection makes the graph
      cyclic;
    * an acyclic result proves that no per-pair selection can be cyclic.
    """
    return _ordered(registry.relationships, registry)


def highest_priority_edges(
    registry: SemanticRegistry,
) -> tuple[SemanticRelationship, ...]:
    """Return the highest-priority relationship of every node pair.

    This is the default runtime selection. Edges of one pair that share the
    top priority are resolved by taking the smallest relationship name, so the
    result stays deterministic.
    """
    return _ordered(
        (
            _preferred(candidates, highest=True)
            for candidates in _grouped(registry).values()
        ),
        registry,
    )


def lowest_priority_edges(
    registry: SemanticRegistry,
) -> tuple[SemanticRelationship, ...]:
    """Return the lowest-priority relationship of every node pair.

    This is the opposite extreme of the default selection, useful for checking
    whether a model stays acyclic under the least preferred edges. Edges of one
    pair that share the lowest priority are resolved by taking the smallest
    relationship name, matching the tie-break of
    :func:`highest_priority_edges`.
    """
    return _ordered(
        (
            _preferred(candidates, highest=False)
            for candidates in _grouped(registry).values()
        ),
        registry,
    )


def edges_for_selection(
    registry: SemanticRegistry,
    selection: Mapping[EntityIdPair, int],
) -> tuple[SemanticRelationship, ...]:
    """Return one relationship per node pair, following an explicit selection.

    Args:
        registry: Registry holding the relationships to choose from.
        selection: Priority to use for a pair, keyed by
            ``(source entity id, target entity id)``. Pairs missing from the
            mapping, or mapped to ``None``, fall back to their highest-priority
            relationship.

    Raises:
        ValueError: If a selected pair has no relationship at that priority.
    """
    chosen: list[SemanticRelationship] = []
    for pair, candidates in _grouped(registry).items():
        wanted = selection.get(pair)
        if wanted is None:
            chosen.append(_preferred(candidates, highest=True))
            continue
        matches = [item for item in candidates if item.priority == wanted]
        if not matches:
            raise ValueError(
                f"No relationship from {pair[0]} to {pair[1]} at priority {wanted}"
            )
        chosen.append(max(matches, key=lambda item: item.name))
    return _ordered(chosen, registry)


def edges_by_priority(
    registry: SemanticRegistry,
) -> dict[int, tuple[SemanticRelationship, ...]]:
    """Group relationships by their own priority value.

    Each value answers "is this priority level self-consistent on its own?",
    which is weaker than the runtime graph because runtime selections may mix
    priorities across different node pairs. This does not prove the runtime
    graph is acyclic: different node pairs may mix priorities. Use
    :func:`all_edges` for a worst-case check and :func:`edges_for_selection`
    for a specific runtime selection.
    """
    groups: dict[int, list[SemanticRelationship]] = {}
    for relationship in registry.relationships:
        groups.setdefault(relationship.priority, []).append(relationship)
    return {
        priority: _ordered(groups[priority], registry) for priority in sorted(groups)
    }
