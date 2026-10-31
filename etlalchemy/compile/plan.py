"""Plan the joins, CTEs and aggregation grain of a resolved query.

Join planning keeps the statement minimal and explicit:

* only entities the query references — its dimensions, measures, filter fields
  and ordering aliases — are joined, so relationships selected by the routes
  but never used by the query never reach the SQL;
* join types follow cardinality and filter direction: a one-to-many edge joins
  with LEFT so every row of its many end survives a missing match, many-to-many
  edges join with INNER, edges that propagate filters in both directions join
  with INNER because filters can arrive from either side, and one-to-one edges
  join with LEFT;
* an entity that is unreachable from the base through the selected
  relationships raises ``ValueError`` instead of being silently dropped.

Join type selection: a ONE_TO_MANY relationship joins with LEFT in the SINGLE
filter direction, whichever end holds the base entity, so a fact row without a
matching dimension row is kept and its dimension columns come out NULL. BOTH
edges join with INNER because filters can arrive from either side, MANY_TO_MANY
edges join with INNER because they multiply rows, and ONE_TO_ONE edges join with
LEFT so a missing match never truncates the base.

A LEFT JOIN whose target side is also filtered degenerates into an INNER JOIN:
the unmatched rows produce NULL target columns, which the filter then drops. The
first version keeps the LEFT JOIN but records a warning in the ``CompileReport``
saying the result behaves like an INNER JOIN.

The plan never reads a relationship's key columns: it only needs the entity
aliases of each edge, so equi joins and expression joins are planned alike. The
``ON`` predicate itself is produced later by ``relationship.condition``.

Multi-fact queries are planned as one pre-aggregation CTE per fact entity
(``group_measures_by_entity`` + ``plan_ctes``) and a merge query that joins the
CTEs by the full dimension set (``plan_merge``). A single fact entity keeps the
plain single-select plan and emits no CTE.

A dimension that a fact entity cannot reach through the selected relationships
is handled by ``unreachable_dimensions``:

* ``"error"`` (default) raises ``ValueError`` naming the entity and dimension;
* ``"null"`` projects ``NULL`` for that dimension inside the CTE, lets the merge
  query ``COALESCE`` the dimension values, and records a warning in the
  ``CompileReport``.

Filter pushdown: a filter predicate is pushed to every CTE whose join path can
reach the entity referenced by the predicate, not only to the CTE that owns the
measure. One filter may therefore appear in the WHERE clause of several CTEs.

A predicate spanning several facts is split on ``AND``, while an ``OR`` spanning
several facts is rejected because it cannot be pushed into a single CTE.
Predicates referencing a shared dimension are pushed into every CTE that can
reach that dimension.

Fanout detection: for each measure, the compiler walks its join paths and marks
reverse ONE_TO_MANY joins and MANY_TO_MANY joins. SUM, COUNT and AVG raise
ValueError; MIN, MAX and COUNT DISTINCT only warn. MANY_TO_MANY always raises.
"""

from __future__ import annotations

import dataclasses
from collections import deque

from etlalchemy.compile.context import CompileContext
from etlalchemy.compile.report import (
    BOTH_FILTER_FORCES_INNER,
    LEFT_JOIN_FILTERED,
    CompileEvent,
)
from etlalchemy.compile.resolve import (
    ResolvedDimension,
    ResolvedMeasure,
    ResolvedQuery,
    predicate_fields,
)
from etlalchemy.semantic.expression import FieldComparison, Logical, OrderBy, Predicate
from etlalchemy.semantic.join import ExpressionJoin
from etlalchemy.semantic.model import SemanticRegistry
from etlalchemy.semantic.relationship import (
    Cardinality,
    FilterDirection,
    SemanticRelationship,
)
from etlalchemy.semantic.rowset import SemanticEntity

#: Neighbour of one entity in the undirected view of the selected edges.
_Neighbour = tuple[str, SemanticRelationship]
#: Error message used when a route pair is not usable.
_UNREACHABLE_DIMENSIONS = frozenset({"error", "null"})


@dataclasses.dataclass(frozen=True)
class JoinStep:
    """One join of a newly reached entity onto the tables joined so far.

    ``relationship`` is the edge the join walks, ``joined_alias`` is the alias
    of the entity already present in the plan (the BFS parent), ``new_alias``
    is the alias of the entity being joined, ``reversed_edge`` records that the
    walk went from the relationship target to its source, and ``join_type`` is
    ``"INNER"`` or ``"LEFT"``.

    join_type is LEFT for a ONE_TO_MANY edge in the SINGLE direction, INNER for
    BOTH and MANY_TO_MANY edges, and LEFT for a ONE_TO_ONE edge.

    ``filter_pushed`` is set when the edge propagates filters in one direction
    only (``SINGLE``) and every filter on this edge sits on its source side, so
    the predicate could be pushed into the source subquery; the first version
    keeps such predicates in the outer WHERE clause, which is equivalent for a
    LEFT JOIN. ``semi_join`` is reserved for a ``WHERE EXISTS`` rewrite and is
    always False in the first version.
    """

    relationship: SemanticRelationship
    joined_alias: str
    new_alias: str
    reversed_edge: bool
    join_type: str
    filter_pushed: bool = False
    semi_join: bool = False

    @property
    def source_alias(self) -> str:
        """Return the alias of the relationship source endpoint."""
        return self.relationship.source_alias()

    @property
    def target_alias(self) -> str:
        """Return the alias of the relationship target endpoint."""
        return self.relationship.target_alias()


@dataclasses.dataclass(frozen=True)
class CTEPlan:
    """One pre-aggregation CTE for a group of measures.

    ``name`` is the CTE alias, ``entity_alias`` the fact entity it aggregates,
    ``dimensions`` the dimensions it can provide, ``null_dimensions`` the
    dimensions it can only provide as ``NULL``, ``measures`` its aggregates,
    ``join_paths`` the relationships it joins, ``filters`` the predicates
    pushed into it and ``steps`` the direction-aware joins derived from
    ``join_paths``.

    filters include every predicate whose referenced entity is reachable from
    this CTE's join paths, including predicates owned by other entities.
    """

    name: str
    entity_alias: str
    dimensions: tuple[ResolvedDimension, ...]
    null_dimensions: tuple[ResolvedDimension, ...]
    measures: tuple[ResolvedMeasure, ...]
    join_paths: tuple[SemanticRelationship, ...]
    filters: tuple[Predicate, ...]
    steps: tuple[JoinStep, ...] = ()


@dataclasses.dataclass(frozen=True)
class MergePlan:
    """Main query that merges CTEs by dimension.

    ``dimensions`` is the full dimension set of the query, ``ctes`` the
    pre-aggregations to merge, and ``order_terms``/``row_limit`` apply to the
    merged result.
    """

    dimensions: tuple[ResolvedDimension, ...]
    ctes: tuple[CTEPlan, ...]
    order_terms: tuple[OrderBy, ...]
    row_limit: int | None


@dataclasses.dataclass(frozen=True)
class JoinPlan:
    """Base entity, join order, grouping grain and projections of a query.

    steps only include edges needed to connect the base entity to the entities
    referenced by the query.
    """

    base_entity: SemanticEntity
    steps: tuple[JoinStep, ...]
    group_by: tuple[ResolvedDimension, ...]
    aggregations: tuple[ResolvedMeasure, ...]
    filters: tuple[Predicate, ...]
    order_terms: tuple[OrderBy, ...]
    row_limit: int | None


@dataclasses.dataclass(frozen=True)
class _BfsTree:
    """Breadth-first tree over the undirected selected edges."""

    parent: dict[str, tuple[str, SemanticRelationship]]
    discovery: dict[str, int]


@dataclasses.dataclass(frozen=True)
class FanoutRisk:
    """One fanout risk discovered on a measure's join path.

    ``measure`` is the measure name, ``entity_alias`` the entity that owns it,
    ``relationship`` the edge that can duplicate the measure rows, ``reason`` is
    ``"one_to_many_reverse"`` when the measure sits on the one end of a
    ONE_TO_MANY edge and ``"many_to_many"`` for a MANY_TO_MANY edge, and
    ``severity`` is ``"error"`` or ``"warning"`` for the measure's aggregation.
    """

    measure: str
    entity_alias: str
    relationship: str
    reason: str
    severity: str


#: Aggregations whose value changes when a join duplicates the measure rows.
_STRICT_FANOUT_AGGREGATIONS = frozenset({"avg", "count", "sum"})


def _append_unique(aliases: list[str], alias: str) -> None:
    """Append an alias once, in first-seen order."""
    if alias not in aliases:
        aliases.append(alias)


def referenced_entities(resolved: ResolvedQuery) -> tuple[str, ...]:
    """Return the entity aliases the query actually references.

    The aliases come from the dimensions, the measures, the fields used by the
    filters and the entities behind the ordering aliases, in first-seen order.
    """
    aliases: list[str] = []
    for dimension in resolved.dimensions:
        _append_unique(aliases, dimension.entity.alias)
    for measure in resolved.measures:
        _append_unique(aliases, measure.entity.alias)
    for predicate in resolved.filters:
        for ref in predicate_fields(predicate):
            _append_unique(aliases, ref.entity)

    entities_by_output: dict[str, str] = {
        dimension.output_alias: dimension.entity.alias
        for dimension in resolved.dimensions
    }
    entities_by_output.update(
        {measure.output_alias: measure.entity.alias for measure in resolved.measures}
    )
    for term in resolved.order_terms:
        entity_alias = entities_by_output.get(term.ref)
        if entity_alias is not None:
            _append_unique(aliases, entity_alias)
    return tuple(aliases)


def choose_base_entity(resolved: ResolvedQuery, referenced: tuple[str, ...]) -> str:
    """Pick the FROM entity for the query.

    Aggregating queries start at the first measure's entity, because the fact
    table drives the grain; queries without measures start at the first
    dimension's entity.

    Raises:
        ValueError: If the query has neither dimensions nor measures.
    """
    if resolved.measures:
        return resolved.measures[0].entity.alias
    if resolved.dimensions:
        return resolved.dimensions[0].entity.alias
    raise ValueError(
        f"Query has no dimensions or measures (referenced entities: {referenced})"
    )


def _undirected_edges(
    selected_edges: tuple[SemanticRelationship, ...],
) -> dict[str, tuple[_Neighbour, ...]]:
    """Return alias -> neighbours for the undirected view of the edges.

    Parallel relationships between the same two entities are collapsed to one
    edge, preferring the highest priority and then the smallest name so the
    result stays deterministic.
    """
    candidates: dict[str, dict[str, list[SemanticRelationship]]] = {}
    for relationship in selected_edges:
        source_alias = relationship.source_alias()
        target_alias = relationship.target_alias()
        candidates.setdefault(source_alias, {}).setdefault(target_alias, []).append(
            relationship
        )
        candidates.setdefault(target_alias, {}).setdefault(source_alias, []).append(
            relationship
        )

    adjacency: dict[str, tuple[_Neighbour, ...]] = {}
    for alias, neighbours in candidates.items():
        pairs = [
            (neighbour, min(options, key=lambda item: (-item.priority, item.name)))
            for neighbour, options in neighbours.items()
        ]
        adjacency[alias] = tuple(
            sorted(pairs, key=lambda pair: (pair[0], pair[1].name))
        )
    return adjacency


def _bfs(base_alias: str, selected_edges: tuple[SemanticRelationship, ...]) -> _BfsTree:
    """Walk the selected edges breadth-first from the base entity."""
    adjacency = _undirected_edges(selected_edges)
    parent: dict[str, tuple[str, SemanticRelationship]] = {}
    discovery: dict[str, int] = {}
    visited = {base_alias}
    queue: deque[str] = deque([base_alias])
    index = 0
    while queue:
        current = queue.popleft()
        for neighbour, relationship in adjacency.get(current, ()):
            if neighbour in visited:
                continue
            visited.add(neighbour)
            parent[neighbour] = (current, relationship)
            discovery[neighbour] = index
            index += 1
            queue.append(neighbour)
    return _BfsTree(parent=parent, discovery=discovery)


def _validate_referenced(
    base_alias: str,
    referenced: tuple[str, ...],
    tree: _BfsTree,
    registry: SemanticRegistry,
) -> None:
    """Reject referenced entities that are unknown or unreachable.

    Raises:
        ValueError: If an alias is not registered or has no path from the base.
    """
    known = set(registry.entities)
    known.update(entity.alias for entity in registry.entities.values())
    for alias in referenced:
        if alias not in known:
            raise ValueError(f"Entity {alias!r} is not registered in the model")
        if alias != base_alias and alias not in tree.parent:
            raise ValueError(
                f"Entity {alias!r} is not reachable from base entity "
                f"{base_alias!r} with the selected relationships"
            )


def _needed_edges(
    base_alias: str,
    referenced: tuple[str, ...],
    tree: _BfsTree,
) -> dict[str, SemanticRelationship]:
    """Map every alias on a path from the base to its parent edge."""
    needed: dict[str, SemanticRelationship] = {}
    for alias in referenced:
        node = alias
        while node != base_alias:
            parent_alias, relationship = tree.parent[node]
            needed[node] = relationship
            node = parent_alias
    return needed


def _validate_condition(relationship: SemanticRelationship) -> None:
    """Reject expression joins that need bidirectional filters.

    Raises:
        ValueError: If an expression join uses ``filter_direction="BOTH"``.
    """
    if (
        isinstance(relationship.condition, ExpressionJoin)
        and relationship.filter_direction is FilterDirection.BOTH
    ):
        raise ValueError(
            "expression joins only support filter_direction='SINGLE' in the "
            "first version"
        )


def _steps_from_edges(
    base_alias: str,
    needed: dict[str, SemanticRelationship],
    tree: _BfsTree,
) -> tuple[JoinStep, ...]:
    """Turn needed BFS edges into direction-aware join steps."""
    steps: list[JoinStep] = []
    for alias in sorted(needed, key=lambda name: tree.discovery[name]):
        relationship = needed[alias]
        _validate_condition(relationship)
        parent_alias = tree.parent[alias][0]
        reversed_edge = relationship.source_alias() == alias
        new_alias = (
            relationship.source_alias()
            if reversed_edge
            else relationship.target_alias()
        )
        steps.append(
            JoinStep(
                relationship=relationship,
                joined_alias=parent_alias,
                new_alias=new_alias,
                reversed_edge=reversed_edge,
                join_type=choose_join_type(relationship, base_alias),
            )
        )
    return tuple(steps)


def plan_join_paths(
    base_alias: str,
    referenced: tuple[str, ...],
    selected_edges: tuple[SemanticRelationship, ...],
    registry: SemanticRegistry,
) -> tuple[SemanticRelationship, ...]:
    """Return only the edges needed to connect base to referenced entities.

    Args:
        base_alias: Entity alias the FROM clause starts from.
        referenced: Entity aliases the query references.
        selected_edges: Relationships chosen by the routes.
        registry: Model registry used to validate the aliases.

    Returns:
        The relationships on the paths from the base to every referenced
        entity, ordered by their first appearance in the breadth-first walk.

    Raises:
        ValueError: If a referenced entity is unknown or unreachable.
    """
    tree = _bfs(base_alias, selected_edges)
    _validate_referenced(base_alias, referenced, tree, registry)
    needed = _needed_edges(base_alias, referenced, tree)
    return tuple(
        needed[alias] for alias in sorted(needed, key=lambda name: tree.discovery[name])
    )


def choose_join_type(
    relationship: SemanticRelationship,
    base_alias: str,
) -> str:
    """Return ``"INNER"`` or ``"LEFT"`` for one relationship edge.

    The rules are deliberately conservative:

    * a one-to-many edge joins with LEFT in the SINGLE direction, whatever end
      holds the base entity: the rows of the many end must survive a missing
      match, and their dimension columns become NULL instead;
    * an edge that propagates filters in both directions joins with INNER,
      because filters can arrive from either side and a LEFT JOIN would keep
      rows that should have been filtered out;
    * many-to-many edges join with INNER as well; such a join can multiply
      rows, so the caller has to confirm the resulting grain;
    * one-to-one edges join with LEFT so the base entity is never truncated.

    ``base_alias`` is accepted for callers that already know the base entity
    and is reserved for future use: a semi-join rewrite or an INNER rewrite
    when a WHERE clause filters the target side would need it. The current
    rules do not branch on it.
    """
    # Reserved for a future semi-join / target-filter rewrite.
    _ = base_alias
    if relationship.filter_direction is FilterDirection.BOTH:
        return "INNER"
    if relationship.cardinality is Cardinality.MANY_TO_MANY:
        return "INNER"
    return "LEFT"


def _fanout_reason(
    relationship: SemanticRelationship,
    measure_side_alias: str,
) -> str | None:
    """Return why one edge can fan out a measure, or ``None`` when it cannot.

    ``measure_side_alias`` is the endpoint of the edge that sits closer to the
    measure's entity, so the path walks from the other endpoint towards it.
    """
    if relationship.cardinality is Cardinality.MANY_TO_MANY:
        return "many_to_many"
    if relationship.cardinality is not Cardinality.ONE_TO_MANY:
        return None
    if measure_side_alias == relationship.source_alias():
        return "one_to_many_reverse"
    return None


def _fanout_severity(aggregation: str, reason: str) -> str:
    """Return the severity of one fanout risk for a measure aggregation."""
    if reason == "many_to_many":
        return "error"
    if aggregation in _STRICT_FANOUT_AGGREGATIONS:
        return "error"
    return "warning"


def detect_fanout(
    resolved: ResolvedQuery,
    selected_edges: tuple[SemanticRelationship, ...],
    registry: SemanticRegistry,
) -> tuple[FanoutRisk, ...]:
    """Return fanout risks for every measure in the query.

    The check is static: it walks the join paths from each measure's entity to
    the query dimensions and inspects every edge. An edge duplicates the
    measure rows when it is MANY_TO_MANY, or when it is ONE_TO_MANY and the
    measure's entity sits on its source (one) end. A measure on the target end
    of a ONE_TO_MANY edge is not at risk, because that join does not multiply
    its rows.

    Args:
        resolved: Query whose references are already resolved.
        selected_edges: Relationships chosen by the routes.
        registry: Model registry used to restrict the walk to known entities.

    Returns:
        One risk per (measure, relationship) pair, ordered by measure name and
        then relationship name. The same relationship is reported once per
        measure even when several paths use it.
    """
    known_aliases = {entity.alias for entity in registry.entities.values()}
    targets = tuple(
        dimension.entity.alias
        for dimension in resolved.dimensions
        if dimension.entity.alias in known_aliases
    )

    risks: dict[tuple[str, str], FanoutRisk] = {}
    for measure in resolved.measures:
        entity_alias = measure.entity.alias
        tree = _bfs(entity_alias, selected_edges)
        for target in targets:
            node = target
            while node != entity_alias and node in tree.parent:
                parent_alias, relationship = tree.parent[node]
                reason = _fanout_reason(relationship, parent_alias)
                if reason is not None:
                    risks.setdefault(
                        (measure.ref.name, relationship.name),
                        FanoutRisk(
                            measure=measure.ref.name,
                            entity_alias=entity_alias,
                            relationship=relationship.name,
                            reason=reason,
                            severity=_fanout_severity(
                                measure.measure.aggregation, reason
                            ),
                        ),
                    )
                node = parent_alias
    return tuple(risks[key] for key in sorted(risks))


def _ensure_single_fact_table(resolved: ResolvedQuery) -> None:
    """Reject multi-fact queries in the single-select planner.

    Raises:
        ValueError: If the measures span more than one entity.
    """
    entities = {measure.entity.alias for measure in resolved.measures}
    if len(entities) > 1:
        listed = " and ".join(repr(alias) for alias in sorted(entities))
        raise ValueError(
            "plan_joins supports a single fact entity; compile multi-fact "
            f"queries through plan_ctes instead (got {listed})"
        )


def _entity_for_alias(alias: str, resolved: ResolvedQuery) -> SemanticEntity:
    """Return the entity object behind a query alias.

    Raises:
        ValueError: If the alias is not part of the resolved query.
    """
    for entity in resolved.entities:
        if entity.alias == alias:
            return entity
    raise ValueError(f"Entity {alias!r} is not part of the query")


def _filter_aliases(resolved: ResolvedQuery) -> set[str]:
    """Return the entity aliases referenced by the query filters."""
    aliases: set[str] = set()
    for predicate in resolved.filters:
        aliases.update(ref.entity for ref in predicate_fields(predicate))
    return aliases


def _build_steps(
    base_alias: str,
    referenced: tuple[str, ...],
    tree: _BfsTree,
    resolved: ResolvedQuery,
    context: CompileContext,
) -> tuple[JoinStep, ...]:
    """Turn the needed BFS edges into join steps.

    Each step records whether its filters may be pushed into the source side
    and whether a semi-join would be needed. Two target-side asymmetries are
    reported as structured :class:`~etlalchemy.compile.report.CompileEvent`
    events: a ``BOTH`` edge with a target-side filter is joined with INNER (the
    filter forces it), and a LEFT step whose target entity is filtered in the
    WHERE clause keeps its LEFT type but behaves like an INNER JOIN, because
    the filter drops the rows the LEFT JOIN kept with NULL target columns.
    """
    needed = _needed_edges(base_alias, referenced, tree)
    filtered = _filter_aliases(resolved)
    steps: list[JoinStep] = []
    for step in _steps_from_edges(base_alias, needed, tree):
        relationship = step.relationship
        source_filtered = relationship.source_alias() in filtered
        target_filtered = relationship.target_alias() in filtered
        filter_pushed = (
            relationship.filter_direction is FilterDirection.SINGLE and source_filtered
        )
        if relationship.filter_direction is FilterDirection.BOTH and target_filtered:
            context.report.add(
                CompileEvent(
                    code=BOTH_FILTER_FORCES_INNER,
                    severity="warning",
                    message=(
                        "filter_direction BOTH with a target-side filter on "
                        f"relationship {relationship.name!r} forces an INNER JOIN"
                    ),
                    phase="plan",
                    relationship=relationship.name,
                    join_type="INNER",
                )
            )
        if step.join_type == "LEFT" and step.target_alias in filtered:
            context.report.add(
                CompileEvent(
                    code=LEFT_JOIN_FILTERED,
                    severity="warning",
                    message=(
                        f"LEFT JOIN on relationship {relationship.name!r} is "
                        "filtered on its target side; the result behaves like an "
                        "INNER JOIN"
                    ),
                    phase="plan",
                    relationship=relationship.name,
                    join_type="LEFT",
                )
            )
        steps.append(dataclasses.replace(step, filter_pushed=filter_pushed))
    return tuple(steps)


def plan_joins(
    resolved: ResolvedQuery,
    edges: tuple[SemanticRelationship, ...],
    context: CompileContext,
) -> JoinPlan:
    """Plan the joins needed to answer a single-fact resolved query.

    Args:
        resolved: Query whose references are already resolved.
        edges: Relationships selected for the query.
        context: Compilation state carrying the model.

    Returns:
        The join plan of the query.

    Raises:
        ValueError: If the query has no projections, spans several fact
            tables, or references an entity unreachable from the base.
    """
    _ensure_single_fact_table(resolved)
    referenced = referenced_entities(resolved)
    base_alias = choose_base_entity(resolved, referenced)
    tree = _bfs(base_alias, edges)
    _validate_referenced(base_alias, referenced, tree, context.model.registry)

    return JoinPlan(
        base_entity=_entity_for_alias(base_alias, resolved),
        steps=_build_steps(base_alias, referenced, tree, resolved, context),
        group_by=resolved.dimensions,
        aggregations=resolved.measures,
        filters=resolved.filters,
        order_terms=resolved.order_terms,
        row_limit=resolved.row_limit,
    )


def group_measures_by_entity(
    resolved: ResolvedQuery,
) -> dict[str, list[ResolvedMeasure]]:
    """Group measures by the entity alias their field belongs to."""
    grouped: dict[str, list[ResolvedMeasure]] = {}
    for measure in resolved.measures:
        grouped.setdefault(measure.entity.alias, []).append(measure)
    return grouped


@dataclasses.dataclass(frozen=True)
class _CTEParts:
    """Intermediate CTE plan before filters are assigned."""

    name: str
    entity_alias: str
    dimensions: tuple[ResolvedDimension, ...]
    null_dimensions: tuple[ResolvedDimension, ...]
    measures: tuple[ResolvedMeasure, ...]
    join_paths: tuple[SemanticRelationship, ...]
    steps: tuple[JoinStep, ...]


def _cte_entities(cte: _CTEParts) -> set[str]:
    """Return the aliases a CTE can evaluate filters for.

    The set holds the fact entity and the dimensions the CTE provides, so a
    shared dimension receives the filter in every CTE that joins it. Entities
    that only appear in the join path but are not aggregated on are skipped, so
    a filter is not duplicated across facts that merely pass through them.
    """
    aliases = {cte.entity_alias}
    aliases.update(dimension.entity.alias for dimension in cte.dimensions)
    return aliases


def _assign_predicate(
    predicate: Predicate,
    entity_sets: dict[str, set[str]],
) -> list[tuple[str, Predicate]]:
    """Assign one predicate to the CTEs that can evaluate it.

    ``In``, ``Between``, ``IsNull``, ``Like`` and ``Not`` are assigned by the
    entities their fields reference, exactly like ``Comparison``. A
    ``FieldComparison`` needs both sides inside one CTE. An ``AND`` is split
    over its operands, while an ``OR`` must fit a single CTE.

    Raises:
        ValueError: If an ``OR`` spans several facts, a field-to-field
            comparison spans several facts, or the predicate cannot be pushed
            into any CTE.
    """
    entities = {ref.entity for ref in predicate_fields(predicate)}
    accepting = [
        alias for alias, available in entity_sets.items() if entities <= available
    ]
    if accepting:
        return [(alias, predicate) for alias in accepting]

    if isinstance(predicate, FieldComparison):
        raise ValueError(
            "field-to-field comparison across fact entities is not supported"
        )

    if isinstance(predicate, Logical) and predicate.operator == "AND":
        assigned: list[tuple[str, Predicate]] = []
        for operand in predicate.operands:
            assigned.extend(_assign_predicate(operand, entity_sets))
        return assigned

    if isinstance(predicate, Logical):
        per_operand: list[set[str]] = []
        for operand in predicate.operands:
            operand_entities = {ref.entity for ref in predicate_fields(operand)}
            per_operand.append(
                {
                    alias
                    for alias, available in entity_sets.items()
                    if operand_entities <= available
                }
            )
        common = set.intersection(*per_operand) if per_operand else set()
        if common:
            return [(alias, predicate) for alias in sorted(common)]
        raise ValueError("OR filter spanning multiple fact entities is not supported")

    raise ValueError(
        f"Filter referencing {sorted(entities)} cannot be pushed into any fact entity"
    )


def _push_filters(
    resolved: ResolvedQuery,
    entity_sets: dict[str, set[str]],
) -> dict[str, list[Predicate]]:
    """Assign every filter to the CTEs that can evaluate it."""
    pushed: dict[str, list[Predicate]] = {alias: [] for alias in entity_sets}
    for predicate in resolved.filters:
        for alias, assigned in _assign_predicate(predicate, entity_sets):
            pushed[alias].append(assigned)
    return pushed


def _reject_cross_cte_counts(resolved: ResolvedQuery) -> None:
    """Reject ``count`` and ``count_distinct`` measures in a multi-fact query.

    Neither can be merged from per-fact CTEs yet: the same value may be counted
    once per CTE, and ``COUNT(*)`` cannot simply be summed either.

    Raises:
        ValueError: If any measure of the query uses ``count`` or
            ``count_distinct``.
    """
    for measure in resolved.measures:
        aggregation = measure.measure.aggregation
        if aggregation in {"count", "count_distinct"}:
            raise ValueError(
                f"{aggregation} across multiple fact entities is not supported yet"
            )


def plan_ctes(
    resolved: ResolvedQuery,
    grouped: dict[str, list[ResolvedMeasure]],
    selected_edges: tuple[SemanticRelationship, ...],
    registry: SemanticRegistry,
    unreachable_dimensions: str,
) -> tuple[CTEPlan, ...]:
    """Build one CTE plan per entity that has measures.

    Args:
        resolved: Query whose references are already resolved.
        grouped: Measures grouped by their entity alias.
        selected_edges: Relationships chosen by the routes.
        registry: Model registry used to validate the aliases.
        unreachable_dimensions: ``"error"`` to reject unreachable dimensions or
            ``"null"`` to project them as NULL.

    Returns:
        One CTE plan per fact entity, in the order the measures appear.

    Raises:
        ValueError: If ``unreachable_dimensions`` is invalid, a dimension is
            unreachable from a fact entity in ``"error"`` mode, or the query
            has a ``count`` or ``count_distinct`` measure while spanning
            several fact entities.
    """
    if unreachable_dimensions not in _UNREACHABLE_DIMENSIONS:
        raise ValueError(
            "unreachable_dimensions must be 'error' or 'null', "
            f"got {unreachable_dimensions!r}"
        )

    if len(grouped) > 1:
        _reject_cross_cte_counts(resolved)

    partial: list[_CTEParts] = []
    for entity_alias, measures in grouped.items():
        tree = _bfs(entity_alias, selected_edges)
        dimensions: list[ResolvedDimension] = []
        null_dimensions: list[ResolvedDimension] = []
        needed: dict[str, SemanticRelationship] = {}
        for dimension in resolved.dimensions:
            dimension_alias = dimension.entity.alias
            if dimension_alias == entity_alias:
                dimensions.append(dimension)
                continue
            if dimension_alias not in tree.parent:
                if unreachable_dimensions == "error":
                    raise ValueError(
                        f"Entity {entity_alias!r} cannot aggregate by dimension "
                        f"{dimension_alias!r}: no path in the selected relationships"
                    )
                null_dimensions.append(dimension)
                continue
            dimensions.append(dimension)
            node = dimension_alias
            while node != entity_alias:
                parent_alias, relationship = tree.parent[node]
                needed[node] = relationship
                node = parent_alias

        join_paths = tuple(
            needed[alias]
            for alias in sorted(needed, key=lambda name: tree.discovery[name])
        )
        partial.append(
            _CTEParts(
                name=f"{entity_alias}_agg",
                entity_alias=entity_alias,
                dimensions=tuple(dimensions),
                null_dimensions=tuple(null_dimensions),
                measures=tuple(measures),
                join_paths=join_paths,
                steps=_steps_from_edges(entity_alias, needed, tree),
            )
        )

    entity_sets = {part.name: _cte_entities(part) for part in partial}
    pushed = _push_filters(resolved, entity_sets)

    return tuple(
        CTEPlan(
            name=part.name,
            entity_alias=part.entity_alias,
            dimensions=part.dimensions,
            null_dimensions=part.null_dimensions,
            measures=part.measures,
            join_paths=part.join_paths,
            filters=tuple(pushed[part.name]),
            steps=part.steps,
        )
        for part in partial
    )


def plan_merge(
    resolved: ResolvedQuery,
    ctes: tuple[CTEPlan, ...],
) -> MergePlan:
    """Build the main query plan that merges the CTEs.

    Raises:
        ValueError: If no CTE is given, or if the query has no dimension to
            merge the CTEs on.
    """
    if not ctes:
        raise ValueError("plan_merge requires at least one CTE")
    if len(ctes) > 1 and not resolved.dimensions:
        raise ValueError(
            "Merging several fact entities requires at least one dimension"
        )
    return MergePlan(
        dimensions=resolved.dimensions,
        ctes=ctes,
        order_terms=resolved.order_terms,
        row_limit=resolved.row_limit,
    )


__all__ = [
    "CTEPlan",
    "FanoutRisk",
    "JoinPlan",
    "JoinStep",
    "MergePlan",
    "choose_base_entity",
    "choose_join_type",
    "detect_fanout",
    "group_measures_by_entity",
    "plan_ctes",
    "plan_join_paths",
    "plan_joins",
    "plan_merge",
    "referenced_entities",
]
