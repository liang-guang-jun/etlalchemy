"""Resolve query references against the model they belong to."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from uuid import UUID

from etlalchemy.compile.context import CompileContext
from etlalchemy.compile.report import (
    INVALID_TIME_GRAIN,
    CompileError,
    CompileEvent,
)
from etlalchemy.semantic.expression import (
    Between,
    Comparison,
    FieldComparison,
    FieldRef,
    In,
    IsNull,
    Like,
    MeasureRef,
    Not,
    OrderBy,
    Predicate,
    Query,
    RouteKey,
)
from etlalchemy.semantic.measure import Measure
from etlalchemy.semantic.routing import effective_routes
from etlalchemy.semantic.rowset import Field, SemanticEntity
from etlalchemy.semantic.types import Date, Timestamp


@dataclasses.dataclass(frozen=True)
class ResolvedDimension:
    """A dimension bound to its entity and field.

    ``time_grain`` comes from :attr:`~etlalchemy.semantic.expression.FieldRef.
    time_grain` and is ``None`` when the dimension groups by its raw value.
    """

    ref: FieldRef
    entity: SemanticEntity
    field: Field
    time_grain: str | None = None

    @property
    def output_alias(self) -> str:
        """Return the output name of this dimension."""
        return self.ref.alias or f"{self.ref.entity}__{self.ref.name}"


@dataclasses.dataclass(frozen=True)
class ResolvedMeasure:
    """A measure bound to its definition, entity, fields and effective routes.

    ``field`` is the single column of the aggregation and is ``None`` for a
    multi-column ``count_distinct``, which carries its columns in ``fields``.
    """

    ref: MeasureRef
    measure: Measure
    entity: SemanticEntity
    field: Field | None
    routes: Mapping[RouteKey, int]
    fields: tuple[Field, ...] = ()

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
    """Return every field reference used inside a predicate.

    The walk covers the whole node set: ``Not`` recurses into its operand,
    ``Logical`` unions its operands, ``FieldComparison`` contributes both
    sides, and ``In``, ``Between``, ``IsNull`` and ``Like`` contribute their
    single field.
    """
    if isinstance(predicate, Comparison):
        return (predicate.field,)
    if isinstance(predicate, FieldComparison):
        return (predicate.left, predicate.right)
    if isinstance(predicate, (In, Between, IsNull, Like)):
        return (predicate.field,)
    if isinstance(predicate, Not):
        return predicate_fields(predicate.operand)
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


def _resolve_measure_fields(
    definition: Measure,
    context: CompileContext,
) -> tuple[SemanticEntity, Field | None, tuple[Field, ...]]:
    """Resolve the entity and columns of one measure definition.

    A single-field measure anchors on its ``field``; a multi-column
    ``count_distinct`` anchors on the first entry of ``fields``; a ``COUNT(*)``
    measure has no field at all and anchors on its ``entity`` hint.

    Raises:
        ValueError: If a field is unknown, if the ``fields`` of a measure
            belong to several entities, or if a ``COUNT(*)`` measure does not
            name its entity.
    """
    anchor = definition.field
    if anchor is None and definition.fields:
        anchor = definition.fields[0]
    if anchor is not None:
        entity_alias = anchor.entity
    elif definition.entity is not None:
        entity_alias = definition.entity
    else:
        raise ValueError(
            "COUNT(*) measures must set entity when field and fields are empty"
        )
    entity = resolve_entity(entity_alias, context)

    for ref in definition.fields:
        if ref.entity != entity_alias:
            raise ValueError(
                "count_distinct fields must belong to the same entity as the measure"
            )

    field = (
        None
        if definition.field is None
        else resolve_field(definition.field, context)[1]
    )
    fields = tuple(resolve_field(ref, context)[1] for ref in definition.fields)
    return entity, field, fields


def resolve_query(query: Query, context: CompileContext) -> ResolvedQuery:
    """Resolve the references of a query and record its effective routes.

    A dimension that carries a ``time_grain`` must reference a Date or
    Timestamp field; a grain on any other type is recorded as an
    ``INVALID_TIME_GRAIN`` event and rejected.

    Raises:
        ValueError: If an entity, field, measure or ordering alias is unknown.
        CompileError: If a ``time_grain`` is set on a field that is not a Date
            or Timestamp; ``exc.report`` holds the recorded events.
    """
    dimensions: list[ResolvedDimension] = []
    for dimension_ref in query.dimensions:
        entity, field = resolve_field(dimension_ref, context)
        if dimension_ref.time_grain is not None and not isinstance(
            field.data_type, (Date, Timestamp)
        ):
            message = (
                f"time_grain {dimension_ref.time_grain!r} requires a Date or "
                f"Timestamp field, got {field.data_type.to_string()} on "
                f"{dimension_ref.entity}.{dimension_ref.name}"
            )
            context.report.add(
                CompileEvent(
                    code=INVALID_TIME_GRAIN,
                    severity="error",
                    message=message,
                    phase="resolve",
                    entity=dimension_ref.entity,
                    dimension=dimension_ref.name,
                )
            )
            raise CompileError(message, context.report)
        dimensions.append(
            ResolvedDimension(
                ref=dimension_ref,
                entity=entity,
                field=field,
                time_grain=dimension_ref.time_grain,
            )
        )

    measures: list[ResolvedMeasure] = []
    for measure_ref in query.measures:
        definition = context.model.registry.measures.get(measure_ref.name)
        if definition is None:
            raise ValueError(f"Unknown measure {measure_ref.name!r}")
        measure_entity, measure_field, measure_fields = _resolve_measure_fields(
            definition, context
        )
        routes = effective_routes(definition, query)
        context.measure_routes[measure_ref.name] = routes
        measures.append(
            ResolvedMeasure(
                ref=measure_ref,
                measure=definition,
                entity=measure_entity,
                field=measure_field,
                routes=routes,
                fields=measure_fields,
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
