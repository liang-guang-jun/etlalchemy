"""Application service exposing the semantic use cases."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid4

import structlog
from eventsourcing.asyncio.application import AsyncApplication
from eventsourcing.utils import EnvType

from etlalchemy.catalog.aggregates.errors import UnknownTableError
from etlalchemy.catalog.projection.view import CatalogView
from etlalchemy.semantic.aggregates.errors import InvalidRelationshipError
from etlalchemy.semantic.aggregates.model import Model
from etlalchemy.semantic.aggregates.types import Cardinality, FieldRef, FilterDirection
from etlalchemy.shared.logging import get_logger


def _refs(refs: Sequence[FieldRef]) -> tuple[tuple[str, str], ...]:
    """Converts the command references into the aggregate's tuple form."""
    return tuple((ref.entity, ref.field) for ref in refs)


class ModelApplication(AsyncApplication[UUID]):
    """Application service for the semantic context.

    Each use case loads the model, applies one command and saves the resulting
    events, so every internal entity of the model changes in one unit of work.
    Cross-context checks live here because they need the catalog read model: an
    entity's table must exist, and every relationship reference must name a field
    of the referenced entity's table.
    """

    name = "semantic_application"
    """Application name; the eventsourcing factories derive table names from it."""

    def __init__(self, catalog_view: CatalogView, env: EnvType | None = None) -> None:
        """Wires the catalog read model used to validate tables and fields."""
        super().__init__(env=env)
        self._catalog_view = catalog_view
        self._log: structlog.stdlib.BoundLogger = get_logger("semantic.application")

    # -- model --------------------------------------------------------------

    async def create_model(self, name: str, description: str = "") -> UUID:
        """Creates a semantic model and returns its ID."""
        self._log.info("semantic.model.create start", name=name)
        model = Model(name=name, description=description)
        await self.save(model)
        self._log.info("semantic.model.create done", model_id=str(model.id))
        return model.id

    async def get_model(self, model_id: UUID) -> Model:
        """Returns the model with the given ID."""
        self._log.debug("semantic.model.get start", model_id=str(model_id))
        model = await self._model(model_id)
        self._log.debug("semantic.model.get done", model_id=str(model.id), name=model.name)
        return model

    async def change_model(
        self,
        model_id: UUID,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        """Changes the name and/or description of a model."""
        self._log.info(
            "semantic.model.change start",
            model_id=str(model_id),
            name=name,
            changes_description=description is not None,
        )
        model = await self._model(model_id)
        model.change(name, description)
        await self.save(model)
        self._log.info("semantic.model.change done", model_id=str(model_id))

    async def discard_model(self, model_id: UUID) -> None:
        """Discards a model."""
        self._log.info("semantic.model.discard start", model_id=str(model_id))
        model = await self._model(model_id)
        model.discard()
        await self.save(model)
        self._log.info("semantic.model.discard done", model_id=str(model_id))

    # -- entities -----------------------------------------------------------

    async def add_entity(
        self,
        model_id: UUID,
        entity_name: str,
        table_id: UUID,
    ) -> UUID:
        """Adds an entity backed by the given catalog table and returns its id."""
        self._log.info(
            "semantic.entity.add start",
            model_id=str(model_id),
            entity=entity_name,
            table_id=str(table_id),
        )
        model = await self._model(model_id)
        await self._require_table(table_id)
        entity_id = uuid4()
        model.add_entity(entity_name, table_id, entity_id)
        await self.save(model)
        self._log.info("semantic.entity.add done", model_id=str(model_id), entity=entity_name)
        return entity_id

    async def rename_entity(self, model_id: UUID, old_name: str, new_name: str) -> None:
        """Renames an entity and rewrites the references to it."""
        self._log.info(
            "semantic.entity.rename start",
            model_id=str(model_id),
            old_name=old_name,
            new_name=new_name,
        )
        model = await self._model(model_id)
        model.rename_entity(old_name, new_name)
        await self.save(model)
        self._log.info("semantic.entity.rename done", model_id=str(model_id), name=new_name)

    async def change_entity_table(
        self,
        model_id: UUID,
        entity_name: str,
        table_id: UUID,
    ) -> None:
        """Points an entity at another catalog table."""
        self._log.info(
            "semantic.entity.change_table start",
            model_id=str(model_id),
            entity=entity_name,
            table_id=str(table_id),
        )
        model = await self._model(model_id)
        await self._require_table(table_id)
        model.change_entity_table(entity_name, table_id)
        await self.save(model)
        self._log.info(
            "semantic.entity.change_table done",
            model_id=str(model_id),
            entity=entity_name,
        )

    async def remove_entity(self, model_id: UUID, entity_name: str) -> None:
        """Removes an entity with its relationships and diagram nodes."""
        self._log.info(
            "semantic.entity.remove start",
            model_id=str(model_id),
            entity=entity_name,
        )
        model = await self._model(model_id)
        model.remove_entity(entity_name)
        await self.save(model)
        self._log.info(
            "semantic.entity.remove done",
            model_id=str(model_id),
            entity=entity_name,
        )

    # -- relationships ------------------------------------------------------

    async def add_relationship(
        self,
        model_id: UUID,
        from_refs: list[FieldRef],
        to_refs: list[FieldRef],
        cardinality: Cardinality,
        filter_direction: FilterDirection,
        priority: int = 0,
    ) -> UUID:
        """Adds a relationship between fields of two existing entities."""
        relationship_id = uuid4()
        self._log.info(
            "semantic.relationship.add start",
            model_id=str(model_id),
            relationship_id=str(relationship_id),
            cardinality=str(cardinality),
        )
        model = await self._model(model_id)
        from_pairs = _refs(from_refs)
        to_pairs = _refs(to_refs)
        await self._require_fields(model, from_pairs, to_pairs)
        model.add_relationship(
            relationship_id,
            from_pairs,
            to_pairs,
            cardinality,
            filter_direction,
            priority,
        )
        await self.save(model)
        self._log.info(
            "semantic.relationship.add done",
            model_id=str(model_id),
            relationship_id=str(relationship_id),
        )
        return relationship_id

    async def change_relationship(
        self,
        model_id: UUID,
        relationship_id: UUID,
        from_refs: list[FieldRef] | None = None,
        to_refs: list[FieldRef] | None = None,
        cardinality: Cardinality | None = None,
        filter_direction: FilterDirection | None = None,
        priority: int | None = None,
    ) -> None:
        """Changes the given attributes of an existing relationship."""
        self._log.info(
            "semantic.relationship.change start",
            model_id=str(model_id),
            relationship_id=str(relationship_id),
        )
        model = await self._model(model_id)
        from_pairs = None if from_refs is None else _refs(from_refs)
        to_pairs = None if to_refs is None else _refs(to_refs)
        await self._require_fields(model, from_pairs, to_pairs)
        model.change_relationship(
            relationship_id,
            from_pairs,
            to_pairs,
            cardinality,
            filter_direction,
            priority,
        )
        await self.save(model)
        self._log.info(
            "semantic.relationship.change done",
            model_id=str(model_id),
            relationship_id=str(relationship_id),
        )

    async def remove_relationship(self, model_id: UUID, relationship_id: UUID) -> None:
        """Removes a relationship."""
        self._log.info(
            "semantic.relationship.remove start",
            model_id=str(model_id),
            relationship_id=str(relationship_id),
        )
        model = await self._model(model_id)
        model.remove_relationship(relationship_id)
        await self.save(model)
        self._log.info(
            "semantic.relationship.remove done",
            model_id=str(model_id),
            relationship_id=str(relationship_id),
        )

    # -- diagrams -----------------------------------------------------------

    async def add_diagram(self, model_id: UUID, name: str, order: int = 0) -> None:
        """Adds an empty diagram to the model."""
        self._log.info("semantic.diagram.add start", model_id=str(model_id), name=name)
        model = await self._model(model_id)
        model.add_diagram(name, order)
        await self.save(model)
        self._log.info("semantic.diagram.add done", model_id=str(model_id), name=name)

    async def rename_diagram(self, model_id: UUID, old_name: str, new_name: str) -> None:
        """Renames a diagram, keeping its nodes."""
        self._log.info(
            "semantic.diagram.rename start",
            model_id=str(model_id),
            old_name=old_name,
            new_name=new_name,
        )
        model = await self._model(model_id)
        model.rename_diagram(old_name, new_name)
        await self.save(model)
        self._log.info("semantic.diagram.rename done", model_id=str(model_id), name=new_name)

    async def change_diagram_order(self, model_id: UUID, name: str, order: int) -> None:
        """Changes the sort hint of a diagram."""
        self._log.info(
            "semantic.diagram.change_order start",
            model_id=str(model_id),
            name=name,
            order=order,
        )
        model = await self._model(model_id)
        model.change_diagram_order(name, order)
        await self.save(model)
        self._log.info(
            "semantic.diagram.change_order done",
            model_id=str(model_id),
            name=name,
        )

    async def remove_diagram(self, model_id: UUID, name: str) -> None:
        """Removes a diagram with its nodes."""
        self._log.info("semantic.diagram.remove start", model_id=str(model_id), name=name)
        model = await self._model(model_id)
        model.remove_diagram(name)
        await self.save(model)
        self._log.info("semantic.diagram.remove done", model_id=str(model_id), name=name)

    # -- nodes --------------------------------------------------------------

    async def place_node(
        self,
        model_id: UUID,
        diagram_name: str,
        entity_name: str,
        x: float,
        y: float,
    ) -> None:
        """Places an entity on a diagram."""
        self._log.info(
            "semantic.node.place start",
            model_id=str(model_id),
            diagram=diagram_name,
            entity=entity_name,
        )
        model = await self._model(model_id)
        model.place_node(diagram_name, entity_name, x, y)
        await self.save(model)
        self._log.info(
            "semantic.node.place done",
            model_id=str(model_id),
            diagram=diagram_name,
            entity=entity_name,
        )

    async def move_node(
        self,
        model_id: UUID,
        diagram_name: str,
        entity_name: str,
        x: float,
        y: float,
    ) -> None:
        """Moves a placed entity on a diagram."""
        self._log.info(
            "semantic.node.move start",
            model_id=str(model_id),
            diagram=diagram_name,
            entity=entity_name,
        )
        model = await self._model(model_id)
        model.move_node(diagram_name, entity_name, x, y)
        await self.save(model)
        self._log.info(
            "semantic.node.move done",
            model_id=str(model_id),
            diagram=diagram_name,
            entity=entity_name,
        )

    async def remove_node(self, model_id: UUID, diagram_name: str, entity_name: str) -> None:
        """Removes an entity from a diagram."""
        self._log.info(
            "semantic.node.remove start",
            model_id=str(model_id),
            diagram=diagram_name,
            entity=entity_name,
        )
        model = await self._model(model_id)
        model.remove_node(diagram_name, entity_name)
        await self.save(model)
        self._log.info(
            "semantic.node.remove done",
            model_id=str(model_id),
            diagram=diagram_name,
            entity=entity_name,
        )

    # -- helpers ------------------------------------------------------------

    async def _model(self, model_id: UUID) -> Model:
        """Returns the model with the given ID."""
        model: Model = await self.repository.get(model_id)
        assert isinstance(model, Model)
        return model

    async def _require_table(self, table_id: UUID) -> None:
        """Rejects a table the catalog does not know."""
        table = await self._catalog_view.get_table(table_id)
        if table is None:
            msg = f"Table {table_id} does not exist in the catalog"
            raise UnknownTableError(msg)

    async def _require_fields(
        self,
        model: Model,
        *sides: Sequence[tuple[str, str]] | None,
    ) -> None:
        """Rejects references to fields the catalog does not know.

        The field list of each table is cached, so a relationship that references
        several fields of the same table reads it once.
        """
        field_cache: dict[UUID, set[str]] = {}
        for refs in sides:
            for entity_name, field_name in refs or ():
                entity = model.entities.get(entity_name)
                if entity is None:
                    msg = f"Entity {entity_name!r} does not exist in model {model.name!r}"
                    raise InvalidRelationshipError(msg)
                names = field_cache.get(entity.table_id)
                if names is None:
                    names = {
                        field.name
                        for field in await self._catalog_view.list_fields(entity.table_id)
                    }
                    field_cache[entity.table_id] = names
                if field_name not in names:
                    msg = (
                        f"Field {field_name!r} does not exist in the table of "
                        f"entity {entity_name!r}"
                    )
                    raise InvalidRelationshipError(msg)
