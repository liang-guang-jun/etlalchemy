---
description: "Use when writing or changing event-sourced aggregates, domain events, commands or aggregate errors. Covers @event decorators, frozen dataclass events, validation order and cross-aggregate references."
applyTo: "etlalchemy/**/*.py"
---
# Aggregate and Event Conventions

Aggregates use the `eventsourcing` library (`Aggregate`, `AggregateCreated`,
`event`) with one aggregate root per module under `etlalchemy/<context>/aggregates/`.

## Aggregate shape

- `__init__` sets attributes; it is **not** decorated.
- Declare a nested `Event(Aggregate.Event)` base class, then one frozen dataclass per
  event, each with a docstring and field docstrings.
- The creation event subclasses `AggregateCreated` and mirrors the `__init__`
  parameters (plus `catalog_id`/`schema_id` style references).
- Command methods are bound with `@event(EventClass)`; the method body is both the
  mutation and the replay logic.

```python
class Catalog(Aggregate):
    """Aggregate root that registers the schemas of a data catalog."""

    def __init__(self, name: str, description: str = "") -> None:
        """Initialises a catalog with the given name and description."""
        self.name = name
        self.description = description
        self.schemas: dict[str, UUID] = {}

    class Event(Aggregate.Event):
        """Base class for events raised by the catalog aggregate."""

    @dataclass(frozen=True)
    class Started(AggregateCreated):
        """Recorded when a catalog is created."""

        name: str
        """Name of the new catalog."""
        description: str = ""
        """Free-form description of the new catalog."""

    @dataclass(frozen=True)
    class SchemaRegistered(Event):
        """Recorded when a schema is registered under a name."""

        schema_name: str
        """Name the schema is registered under."""
        schema_id: UUID
        """ID of the schema aggregate."""

    @event(SchemaRegistered)
    def register_schema(self, schema_name: str, schema_id: UUID) -> None:
        """Registers a schema aggregate under the given name."""
        if schema_name in self.schemas:
            msg = f"Schema {schema_name!r} already exists in catalog {self.name!r}"
            raise DuplicateSchemaError(msg)
        self.schemas[schema_name] = schema_id
```

## Rules

- **Never** call `self.trigger_event(...)`; the `@event` decorator triggers it.
- **Never** define `apply()` on an event class. The decorator routes `apply()` through
  `DecoratedFuncCaller`, which calls the command method and then `super().apply()`;
  a parallel `apply()` would mutate twice.
- Command parameters must have the same names as the event fields, and the event must
  declare every parameter the method needs: kwargs are filtered by both signatures.
- Validate first, mutate second. `mutate()` calls `apply()` **before** updating
  `version`/`modified_on` and before appending to `pending_events`, so raising from the
  validation block leaves the aggregate untouched. Never mutate and then raise.
- Name lookups return the referenced id or raise `Unknown<Thing>Error`
  (`catalog.schema_id(name)`, `schema.table_id(name)`).
- Partial updates use one fine-grained event per changed attribute instead of a
  combined event with optional (`None`) fields: `FieldTypeChanged`,
  `FieldNullabilityChanged`. Optional fields inside events are also a serialisation
  hazard (the default `JSONTranscoder` needs one registered `Transcoding` per nested
  value object type), so events carry whole value objects such as `DataType`, never
  `DataType | None`.
- Cross-aggregate references are `UUID`s owned by the parent as `dict[str, UUID]`;
  orchestration (create child, register id, `self.save(parent, child)`) belongs in the
  application, not in an aggregate.
- Domain errors live in `etlalchemy/<context>/aggregates/errors.py`, subclass the
  context base error, and end with `Error` (ruff N818).

## Replay and typing

- Replay is `aggregate = event.mutate(aggregate)` in order; constructors and command
  bodies must therefore be valid for already-applied state.
- `Application.repository.get()` returns an unresolved type: annotate the result
  (`catalog: Catalog = self.repository.get(id)`) or mypy reports `[var-annotated]`.
