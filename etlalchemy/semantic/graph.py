"""Cycle analysis over explicit relationship sets.

``GraphService`` analyses one explicit collection of ``SemanticRelationship``
edges and has no notion of ``priority``. Priority is a local selection group:
each ``(source entity, target entity)`` pair may hold several relationships
with different priorities, and at runtime every pair independently elects one
effective relationship. The choices of different pairs are independent, so
there is no global priority layer and the full set of combinations cannot be
enumerated in advance. Callers therefore decide which edges to analyse;
``etlalchemy.core.selection`` provides the standard choices — all edges for a
worst-case check, highest priority for the default selection, an explicit
selection mapping, or a single priority level at a time.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID

from etlalchemy.semantic.relationship import Cardinality, SemanticRelationship


class CycleKind(StrEnum):
    """Classification of a relationship cycle."""

    SELF_REFERENCE = "SELF_REFERENCE"
    ONE_TO_ONE = "ONE_TO_ONE"
    MANY_TO_MANY = "MANY_TO_MANY"
    MIXED = "MIXED"


class RelationshipCycleError(ValueError):
    """Raised when a model is required to be acyclic but contains a cycle."""


#: Prefix applied to labels of entities absent from ``known_entities``.
UNKNOWN_LABEL_PREFIX = "?"


@dataclass(frozen=True)
class Cycle:
    """A simple directed cycle of entities, anchored at its smallest node.

    ``entities`` holds the labels in traversal order without repeating the
    anchor, so ``a -> b -> a`` is stored as ``("a", "b")``. ``relationships``
    holds the edges in the same order; it is excluded from equality, so two
    cycles are equal when their ``entities`` and ``kind`` match.
    """

    entities: tuple[str, ...]
    kind: CycleKind
    relationships: tuple[SemanticRelationship, ...] = field(
        default=(), compare=False, repr=False
    )

    def __str__(self) -> str:
        """Render the cycle as an arrow path followed by its kind."""
        path = " -> ".join((*self.entities, self.entities[0]))
        return f"{path} ({self.kind})"


def _classify(relationships: Sequence[SemanticRelationship]) -> CycleKind:
    """Classify a closed walk by the cardinalities of its edges.

    Args:
        relationships: Edges forming one closed walk, in traversal order.

    Raises:
        ValueError: If the walk is a single edge that is not a self reference.
    """
    if len(relationships) == 1:
        only = relationships[0]
        if only.source_alias() != only.target_alias():
            raise ValueError(
                f"A single non-self relationship cannot form a cycle: {only.name!r}"
            )
        return CycleKind.SELF_REFERENCE
    cardinalities = {relationship.cardinality for relationship in relationships}
    if cardinalities == {Cardinality.ONE_TO_ONE}:
        return CycleKind.ONE_TO_ONE
    if Cardinality.MANY_TO_MANY in cardinalities:
        return CycleKind.MANY_TO_MANY
    return CycleKind.MIXED


@dataclass(frozen=True)
class _GraphIndex:
    """Immutable adjacency index built from one explicit edge set."""

    nodes: tuple[str, ...]
    adjacency: Mapping[str, tuple[tuple[str, SemanticRelationship], ...]]
    unknown: tuple[tuple[str, str], ...]


def _resolve_label(alias: str, known_aliases: frozenset[str]) -> tuple[str, bool]:
    """Return the display label of an entity alias and whether it is known."""
    if alias in known_aliases:
        return alias, True
    return f"{UNKNOWN_LABEL_PREFIX}{alias}", False


def _build_index(
    relationships: Iterable[SemanticRelationship],
    known_entities: Mapping[UUID, str],
) -> _GraphIndex:
    """Index an explicit edge set by source alias, target alias and name."""
    known_aliases = frozenset(known_entities.values())
    adjacency: dict[str, list[tuple[str, SemanticRelationship]]] = {}
    unknown: set[tuple[str, str]] = set()
    for relationship in relationships:
        source, source_known = _resolve_label(
            relationship.source_alias(), known_aliases
        )
        target, target_known = _resolve_label(
            relationship.target_alias(), known_aliases
        )
        if not source_known:
            unknown.add((relationship.name, source))
        if not target_known:
            unknown.add((relationship.name, target))
        adjacency.setdefault(source, []).append((target, relationship))
        adjacency.setdefault(target, [])
    frozen = {
        node: tuple(sorted(edges, key=lambda edge: (edge[0], edge[1].name)))
        for node, edges in adjacency.items()
    }
    return _GraphIndex(
        nodes=tuple(sorted(frozen)),
        adjacency=MappingProxyType(frozen),
        unknown=tuple(sorted(unknown)),
    )


class GraphService:
    """Cycle detection over one explicit set of relationships.

    The service never reads ``SemanticRelationship.priority``: the caller picks
    the edge set and the service judges only that set. Priorities are local
    selection groups per ``(source entity, target entity)`` pair, so there is no
    global layer to analyse; use ``etlalchemy.core.selection`` to build the edge
    set for a worst-case check, the default (highest priority) selection, an
    explicit selection, or a single priority level.

    Labels come from ``known_entities`` when an entity id is mapped there.
    Entities missing from that mapping use their alias prefixed with ``?``, so
    unknown labels never collide with known ones.

    Adjacency lists are sorted by ``(target, relationship name)`` and nodes are
    sorted, so every result is deterministic regardless of input order.

    Cycle enumeration is exponential in the worst case (a dense graph has
    exponentially many simple cycles) and is meant for models of the size a
    human authors by hand; prefer ``has_cycle`` when only a boolean is needed.
    """

    def __init__(
        self,
        relationships: Iterable[SemanticRelationship],
        known_entities: Mapping[UUID, str] | None = None,
    ) -> None:
        """Index an explicit relationship set with optional display labels."""
        self._index = _build_index(relationships, known_entities or {})

    @property
    def nodes(self) -> tuple[str, ...]:
        """Return every entity label in sorted order."""
        return self._index.nodes

    @property
    def edges(self) -> tuple[tuple[str, str, str], ...]:
        """Return ``(source, target, relationship name)`` triples."""
        return tuple(
            (source, target, relationship.name)
            for source in self._index.nodes
            for target, relationship in self._index.adjacency[source]
        )

    def neighbors(self, node: str) -> tuple[str, ...]:
        """Return the sorted successor labels of ``node``.

        Raises:
            KeyError: If ``node`` is not part of the analysed edge set, with
                the message ``Unknown node '...'``.
        """
        adjacency = self._index.adjacency
        if node not in adjacency:
            raise KeyError(f"Unknown node {node!r}")
        return tuple(target for target, _ in adjacency[node])

    def has_cycle(self) -> bool:
        """Return whether the edge set contains at least one cycle.

        Uses Kahn's topological sort, which runs in ``O(V + E)`` and never
        allocates cycle objects.
        """
        adjacency = self._index.adjacency
        nodes = self._index.nodes
        indegree = dict.fromkeys(nodes, 0)
        for source in nodes:
            for target, _ in adjacency[source]:
                indegree[target] += 1
        ready = [node for node in nodes if indegree[node] == 0]
        visited = 0
        while ready:
            source = ready.pop()
            visited += 1
            for target, _ in adjacency[source]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)
        return visited != len(nodes)

    def find_cycles(self) -> tuple[Cycle, ...]:
        """Return each distinct simple cycle, anchored at its smallest node.

        Parallel relationships between the same pair of entities can produce
        the same node sequence with different edges; such cycles compare equal
        on ``(entities, kind)``, so the first one is reported and the rest are
        dropped. Traversal only descends into labels greater than the anchor,
        which already visits every node sequence once.
        """
        adjacency = self._index.adjacency
        nodes = self._index.nodes
        order = {node: index for index, node in enumerate(nodes)}
        unique: dict[tuple[tuple[str, ...], CycleKind], Cycle] = {}
        for start in nodes:
            path = [start]
            on_path = {start}
            walked: list[SemanticRelationship] = []
            stack = [iter(adjacency[start])]
            while stack:
                try:
                    target, relationship = next(stack[-1])
                except StopIteration:
                    stack.pop()
                    on_path.discard(path.pop())
                    if walked:
                        walked.pop()
                    continue
                if target == start:
                    closed = (*walked, relationship)
                    cycle = Cycle(
                        entities=tuple(path),
                        kind=_classify(closed),
                        relationships=closed,
                    )
                    unique.setdefault((cycle.entities, cycle.kind), cycle)
                elif target not in on_path and order[target] > order[start]:
                    path.append(target)
                    on_path.add(target)
                    walked.append(relationship)
                    stack.append(iter(adjacency[target]))
        return tuple(unique.values())

    def validate(self) -> tuple[str, ...]:
        """Return human-readable problems; an empty tuple means a valid graph."""
        problems = [
            f"Relationship '{name}' references unknown entity '{label}'"
            for name, label in self._index.unknown
        ]
        problems.extend(f"Cycle detected: {cycle}" for cycle in self.find_cycles())
        return tuple(problems)

    def ensure_acyclic(self) -> None:
        """Raise RelationshipCycleError listing every cycle in the edge set."""
        cycles = self.find_cycles()
        if cycles:
            details = "; ".join(str(cycle) for cycle in cycles)
            raise RelationshipCycleError(f"Relationship cycles detected: {details}")
