"""Resolve query references against the model they belong to."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from uuid import UUID

from etlalchemy.compile.context import CompileContext
from etlalchemy.semantic.expression import (
    Comparison,
    FieldRef,
    MeasureRef,
    OrderBy,
    Predicate,
    Query,
    RouteKey,
)
from etlalchemy.semantic.measure import Measure
from etlalchemy.semantic.routing import effective_routes
from etlalchemy.semantic.rowset import Field, SemanticEntity


@dataclasses.dataclass(frozen=True)
class ResolvedDimension:
    """A dimension bound to its entity and field."""

    ref: FieldRef
    entity: SemanticEntity
    field: Field

    @property
    def output_alias(self) -> str:
        """Return the output name of this dimension."""
        return self.ref.alias or f"{self.ref.entity}__{self.ref.name}"


@dataclasses.dataclass(frozen=True)
class ResolvedMeasure:
    """A measure bound to its definition, entity, field and effective routes."""

    ref: MeasureRef
    measure: Measure
    entity: SemanticEntity
    field: Field
    routes: Mapping[RouteKey, int]

    @property
    def output_alias(self) -> str:
        """Return the output name of this measure."""
        return self.ref.alias or self.ref.name


@dataclasses.dataclass(frozen=True)
class ResolvedQuery:
    """A query whose references have been resolved against a model."""

    dimensions: tuple[ResolvedDimension, ...]
    measures: tuple[ResolvedMeasure, ...]
    filters: tuple[Predicate, ...]
    order_terms: tuple[OrderBy, ...]
    row_limit: int | None
    entities: tuple[SemanticEntity, ...]


def resolve_entity(alias: str, context: CompileContext) -> SemanticEntity:
    """Return the entity registered under ``alias``.

    Raises:
        ValueError: If no entity matches the alias.
    """
    entity = context.entity_by_alias.get(alias)
    if entity is None:
        raise ValueError(f"Unknown entity alias {alias!r}")
    return entity


def resolve_field(
    ref: FieldRef, context: CompileContext
) -> tuple[SemanticEntity, Field]:
    """Return the entity and field a FieldRef points at.

    Raises:
        ValueError: If the entity alias or the field name is unknown.
    """
    entity = resolve_entity(ref.entity, context)
    field = entity.relation.fields.get(ref.name)
    if field is None:
        raise ValueError(f"Unknown field {ref.name!r} on entity {ref.entity!r}")
    return entity, field


def predicate_fields(predicate: Predicate) -> tuple[FieldRef, ...]:
    """Return every field reference used inside a predicate."""
    if isinstance(predicate, Comparison):
        return (predicate.field,)
    return tuple(
        ref for operand in predicate.operands for ref in predicate_fields(operand)
    )


def _append_entity(
    entities: list[SemanticEntity],
    seen: set[UUID],
    entity: SemanticEntity,
) -> None:
    """Append an entity once, in first-seen order."""
    if entity.id not in seen:
        seen.add(entity.id)
        entities.append(entity)


def _validate_order_terms(
    order_terms: tuple[OrderBy, ...],
    dimensions: list[ResolvedDimension],
    measures: list[ResolvedMeasure],
) -> None:
    """Ensure every ordering term names an output alias of the query.

    Raises:
        ValueError: If a term does not match any dimension or measure alias.
    """
    known = {dimension.output_alias for dimension in dimensions}
    known.update(measure.output_alias for measure in measures)
    for term in order_terms:
        if term.ref not in known:
            raise ValueError(
                f"Unknown ordering alias {term.ref!r}; expected one of {sorted(known)}"
            )


def resolve_query(query: Query, context: CompileContext) -> ResolvedQuery:
    """Resolve the references of a query and record its effective routes.

    Raises:
        ValueError: If an entity, field, measure or ordering alias is unknown.
    """
    dimensions: list[ResolvedDimension] = []
    for dimension_ref in query.dimensions:
        entity, field = resolve_field(dimension_ref, context)
        dimensions.append(
            ResolvedDimension(ref=dimension_ref, entity=entity, field=field)
        )

    measures: list[ResolvedMeasure] = []
    for measure_ref in query.measures:
        definition = context.model.registry.measures.get(measure_ref.name)
        if definition is None:
            raise ValueError(f"Unknown measure {measure_ref.name!r}")
        entity, field = resolve_field(definition.field, context)
        routes = effective_routes(definition, query)
        context.measure_routes[measure_ref.name] = routes
        measures.append(
            ResolvedMeasure(
                ref=measure_ref,
                measure=definition,
                entity=entity,
                field=field,
                routes=routes,
            )
        )

    entities: list[SemanticEntity] = []
    seen: set[UUID] = set()
    for dimension in dimensions:
        _append_entity(entities, seen, dimension.entity)
    for resolved_measure in measures:
        _append_entity(entities, seen, resolved_measure.entity)
    for predicate in query.filters:
        for ref in predicate_fields(predicate):
            _append_entity(entities, seen, resolve_field(ref, context)[0])

    _validate_order_terms(query.order_terms, dimensions, measures)

    return ResolvedQuery(
        dimensions=tuple(dimensions),
        measures=tuple(measures),
        filters=query.filters,
        order_terms=query.order_terms,
        row_limit=query.row_limit,
        entities=tuple(entities),
    )
