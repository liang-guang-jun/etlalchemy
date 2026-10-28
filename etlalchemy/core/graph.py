"""Graph analysis over the entities and relationships of a registry.

``GraphService`` treats a ``SemanticRegistry`` as a directed graph whose nodes
are entity labels and whose edges are relationships. It detects simple cycles
(including self-references) and reports structural problems so callers can
refuse to traverse a model that cannot be ordered.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from etlalchemy.core.model import SemanticRegistry
from etlalchemy.core.relationship import Cardinality, SemanticRelationship
from etlalchemy.core.rowset import SemanticEntity


class CycleKind(StrEnum):
    """Classification of a relationship cycle."""

    SELF_REFERENCE = "SELF_REFERENCE"
    ONE_TO_ONE = "ONE_TO_ONE"
    MANY_TO_MANY = "MANY_TO_MANY"
    MIXED = "MIXED"


class RelationshipCycleError(ValueError):
    """Raised when a model is required to be acyclic but contains a cycle."""


@dataclass(frozen=True)
class Cycle:
    """A simple directed cycle of entities, anchored at its smallest node.

    ``entities`` holds the labels in traversal order without repeating the
    anchor, so ``a -> b -> a`` is stored as ``("a", "b")``. ``relationships``
    holds the edges in the same order and is excluded from equality so cycles
    from different registries still compare equal.
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
    """Classify a closed walk by its edge cardinalities."""
    if len(relationships) == 1:
        only = relationships[0]
        if only.source.entity.id == only.target.entity.id:
            return CycleKind.SELF_REFERENCE
    cardinalities = {relationship.cardinality for relationship in relationships}
    if cardinalities == {Cardinality.ONE_TO_ONE}:
        return CycleKind.ONE_TO_ONE
    if Cardinality.MANY_TO_MANY in cardinalities:
        return CycleKind.MANY_TO_MANY
    return CycleKind.MIXED


class GraphService:
    """Cycle detection and structural validation for a SemanticRegistry.

    Nodes are labelled with the registry key when the entity is registered and
    with ``SemanticEntity.alias`` otherwise. Adjacency lists are sorted by
    ``(target, relationship name)`` so every result is deterministic regardless
    of registration order.

    Cycle enumeration is exponential in the worst case (a dense graph has
    exponentially many simple cycles); it is intended for models of the size a
    human authors by hand.
    """

    def __init__(self, registry: SemanticRegistry) -> None:
        """Build the adjacency index for a registry."""
        self._labels: dict[UUID, str] = {
            entity.id: name for name, entity in registry.entities.items()
        }
        self._adjacency: dict[str, list[tuple[str, SemanticRelationship]]] = {
            name: [] for name in registry.entities
        }
        unknown: set[tuple[str, str]] = set()
        for relationship in registry.relationships:
            source, source_known = self._resolve(relationship.source.entity)
            target, target_known = self._resolve(relationship.target.entity)
            if not source_known:
                unknown.add((relationship.name, source))
            if not target_known:
                unknown.add((relationship.name, target))
            self._adjacency.setdefault(source, []).append((target, relationship))
            self._adjacency.setdefault(target, [])
        for edges in self._adjacency.values():
            edges.sort(key=lambda edge: (edge[0], edge[1].name))
        self._unknown: tuple[tuple[str, str], ...] = tuple(sorted(unknown))
        self._nodes: tuple[str, ...] = tuple(sorted(self._adjacency))

    def _resolve(self, entity: SemanticEntity) -> tuple[str, bool]:
        """Return the node label and whether the entity is in the registry."""
        label = self._labels.get(entity.id)
        if label is not None:
            return label, True
        return entity.alias, False

    @property
    def nodes(self) -> tuple[str, ...]:
        """Return every entity label in sorted order."""
        return self._nodes

    @property
    def edges(self) -> tuple[tuple[str, str, str], ...]:
        """Return ``(source, target, relationship name)`` triples."""
        return tuple(
            (source, target, relationship.name)
            for source in self._nodes
            for target, relationship in self._adjacency[source]
        )

    def neighbors(self, node: str) -> tuple[str, ...]:
        """Return the sorted successor labels of ``node``."""
        return tuple(target for target, _ in self._adjacency[node])

    def has_cycle(self) -> bool:
        """Return whether the graph contains at least one cycle.

        Uses Kahn's topological sort, which runs in ``O(V + E)`` and never
        allocates the cycles themselves.
        """
        indegree = dict.fromkeys(self._nodes, 0)
        for source in self._nodes:
            for target, _ in self._adjacency[source]:
                indegree[target] += 1
        ready = [node for node in self._nodes if indegree[node] == 0]
        visited = 0
        while ready:
            source = ready.pop()
            visited += 1
            for target, _ in self._adjacency[source]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)
        return visited != len(self._nodes)

    def find_cycles(self) -> tuple[Cycle, ...]:
        """Return every simple cycle, each anchored at its smallest node.

        A cycle is enumerated exactly once because traversal from its anchor
        only descends into labels greater than the anchor.
        """
        order = {node: index for index, node in enumerate(self._nodes)}
        cycles: list[Cycle] = []
        for start in self._nodes:
            path = [start]
            on_path = {start}
            walked: list[SemanticRelationship] = []
            stack = [iter(self._adjacency[start])]
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
                    cycles.append(
                        Cycle(
                            entities=tuple(path),
                            kind=_classify(closed),
                            relationships=closed,
                        )
                    )
                elif target not in on_path and order[target] > order[start]:
                    path.append(target)
                    on_path.add(target)
                    walked.append(relationship)
                    stack.append(iter(self._adjacency[target]))
        return tuple(cycles)

    def validate(self) -> tuple[str, ...]:
        """Return human-readable problems; an empty tuple means the graph is valid."""
        problems = [
            f"Relationship '{name}' references unknown entity '{label}'"
            for name, label in self._unknown
        ]
        problems.extend(f"Cycle detected: {cycle}" for cycle in self.find_cycles())
        return tuple(problems)

    def ensure_acyclic(self) -> None:
        """Raise RelationshipCycleError listing every cycle in the graph."""
        cycles = self.find_cycles()
        if cycles:
            details = "; ".join(str(cycle) for cycle in cycles)
            raise RelationshipCycleError(f"Relationship cycles detected: {details}")
