"""Asynchronous SQLAlchemy implementation of the semantic read model.

SQLAlchemy Core builds the table definitions and the DML statements; they are
executed on the async engine of
:class:`~eventsourcing.asyncio.sqlalchemy.AsyncSQLAlchemyDatastore`, so the view
change and its tracking record still share one transaction. The same class serves
SQLite (``aiosqlite``) and PostgreSQL (``psycopg``); only the upsert dialect
differs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from eventsourcing.asyncio.sqlalchemy import (
    AsyncSQLAlchemyDatastore,
    AsyncSQLAlchemyTrackingRecorder,
)
from sqlalchemy import Select, delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from etlalchemy.semantic.aggregates.model import entity_identity
from etlalchemy.semantic.aggregates.types import ALL_DIAGRAM
from etlalchemy.semantic.projection.tables import (
    metadata,
    semantic_diagrams,
    semantic_entities,
    semantic_models,
    semantic_nodes,
    semantic_relationship_fields,
    semantic_relationships,
)
from etlalchemy.semantic.projection.view import (
    DiagramRow,
    EntityRow,
    ModelRow,
    NodeRow,
    RefPair,
    RelationshipRow,
    SemanticView,
    as_uuid,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from eventsourcing.persistence import Tracking
    from sqlalchemy import Table


def _now() -> datetime:
    """Returns the current UTC timestamp written by soft deletes."""
    return datetime.now(UTC)


def _relationship_ids_of(model_id: UUID) -> Select[Any]:
    """Returns the ids of the relationships owned by a model."""
    return select(semantic_relationships.c.relationship_id).where(
        semantic_relationships.c.model_id == model_id
    )


def _referencing_relationship_ids(model_id: UUID, entity_name: str) -> Select[Any]:
    """Returns the ids of the relationships that reference an entity of a model."""
    return select(semantic_relationship_fields.c.relationship_id).where(
        semantic_relationship_fields.c.entity_name == entity_name,
        semantic_relationship_fields.c.relationship_id.in_(_relationship_ids_of(model_id)),
    )


class SQLAlchemySemanticView(AsyncSQLAlchemyTrackingRecorder, SemanticView):
    """Asynchronous materialised view of the semantic aggregates."""

    async def create_table(self) -> None:
        """Creates the tracking table and the view tables if they do not exist."""
        async with self.datastore.transaction() as conn:
            await conn.run_sync(metadata.create_all)
            await conn.run_sync(self.datastore.metadata.create_all)
            await self._ensure_entity_id_column(conn)

    async def _ensure_entity_id_column(self, conn: Any) -> None:
        """Adds ``entity_id`` to an entity table created before entities had an id.

        The column is added nullable and every legacy row is then given the
        derived identity its events replay to, so old and new rows agree.
        """
        if self.datastore.dialect_name == AsyncSQLAlchemyDatastore.SQLITE:
            result = await conn.exec_driver_sql("PRAGMA table_info(semantic_entities)")
            existing = {str(row._mapping["name"]) for row in result.fetchall()}
            if "entity_id" not in existing:
                await conn.exec_driver_sql(
                    "ALTER TABLE semantic_entities ADD COLUMN entity_id TEXT"
                )
        else:
            await conn.exec_driver_sql(
                "ALTER TABLE semantic_entities ADD COLUMN IF NOT EXISTS entity_id UUID"
            )
        rows = (
            await conn.execute(
                select(semantic_entities.c.model_id, semantic_entities.c.name).where(
                    semantic_entities.c.entity_id.is_(None)
                )
            )
        ).all()
        for row in rows:
            await conn.execute(
                update(semantic_entities)
                .where(
                    semantic_entities.c.model_id == row.model_id,
                    semantic_entities.c.name == row.name,
                )
                .values(entity_id=entity_identity(as_uuid(row.model_id), str(row.name)))
            )

    def _insert(self, table: Table) -> Any:
        """Returns the upsert construct of the configured dialect."""
        if self.datastore.dialect_name == AsyncSQLAlchemyDatastore.SQLITE:
            return sqlite_insert(table)
        return pg_insert(table)

    async def _write(self, statements: Sequence[Any], tracking: Tracking) -> None:
        """Applies the statements and records the tracking row atomically."""
        async with self.transaction() as conn:
            for statement in statements:
                await conn.execute(statement)
            await self.insert_tracking_in_transaction(conn, tracking)

    async def _fetch_all(self, statement: Select[Any]) -> Sequence[Any]:
        """Executes a read statement and returns all rows."""
        async with self.datastore.connection() as conn:
            rows: Sequence[Any] = (await conn.execute(statement)).all()
            return rows

    async def _fetch_one(self, statement: Select[Any]) -> Any:
        """Executes a read statement and returns the first row, or ``None``."""
        async with self.datastore.connection() as conn:
            return (await conn.execute(statement)).first()

    # -- models -------------------------------------------------------------

    async def register_model(
        self,
        model_id: UUID,
        name: str,
        description: str,
        tracking: Tracking,
    ) -> None:
        """Registers a model and its All diagram in one transaction."""
        statement = self._insert(semantic_models).values(
            model_id=model_id,
            name=name,
            description=description,
            discarded_at=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[semantic_models.c.model_id],
            set_={
                "name": statement.excluded.name,
                "description": statement.excluded.description,
                "discarded_at": statement.excluded.discarded_at,
            },
        )
        await self._write([statement, self._diagram_upsert(model_id, ALL_DIAGRAM, 0)], tracking)

    async def change_model(
        self,
        model_id: UUID,
        name: str | None,
        description: str | None,
        tracking: Tracking,
    ) -> None:
        """Changes a model, updating only the non-``None`` attributes."""
        values: dict[str, Any] = {}
        if name is not None:
            values["name"] = name
        if description is not None:
            values["description"] = description
        statements: list[Any] = []
        if values:
            statements.append(
                update(semantic_models)
                .where(semantic_models.c.model_id == model_id)
                .values(**values)
            )
        await self._write(statements, tracking)

    async def discard_model(self, model_id: UUID, tracking: Tracking) -> None:
        """Marks a model as discarded and deletes everything it owned."""
        statements = [
            delete(semantic_relationship_fields).where(
                semantic_relationship_fields.c.relationship_id.in_(_relationship_ids_of(model_id))
            ),
            delete(semantic_relationships).where(semantic_relationships.c.model_id == model_id),
            delete(semantic_nodes).where(semantic_nodes.c.model_id == model_id),
            delete(semantic_diagrams).where(semantic_diagrams.c.model_id == model_id),
            delete(semantic_entities).where(semantic_entities.c.model_id == model_id),
            update(semantic_models)
            .where(semantic_models.c.model_id == model_id)
            .values(discarded_at=_now()),
        ]
        await self._write(statements, tracking)

    async def get_model(self, model_id: UUID) -> ModelRow | None:
        """Returns one live model, or ``None``."""
        row = await self._fetch_one(
            select(semantic_models).where(
                semantic_models.c.model_id == model_id,
                semantic_models.c.discarded_at.is_(None),
            )
        )
        return None if row is None else self._model_row(row)

    async def list_models(self) -> list[ModelRow]:
        """Returns every live model, ordered by name."""
        rows = await self._fetch_all(
            select(semantic_models)
            .where(semantic_models.c.discarded_at.is_(None))
            .order_by(semantic_models.c.name)
        )
        return [self._model_row(row) for row in rows]

    # -- entities -----------------------------------------------------------

    async def register_entity(
        self,
        model_id: UUID,
        name: str,
        table_id: UUID,
        x: float,
        y: float,
        tracking: Tracking,
        entity_id: UUID | None = None,
    ) -> None:
        """Registers an entity and places its node on the All diagram."""
        statement = self._insert(semantic_entities).values(
            model_id=model_id,
            entity_id=entity_id or entity_identity(model_id, name),
            name=name,
            table_id=table_id,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[semantic_entities.c.model_id, semantic_entities.c.name],
            set_={"table_id": statement.excluded.table_id},
        )
        await self._write(
            [statement, self._node_upsert(model_id, ALL_DIAGRAM, name, x, y)],
            tracking,
        )

    async def rename_entity(
        self,
        model_id: UUID,
        old_name: str,
        new_name: str,
        tracking: Tracking,
    ) -> None:
        """Renames an entity and rewrites the references and nodes that use it."""
        statements = [
            update(semantic_entities)
            .where(
                semantic_entities.c.model_id == model_id,
                semantic_entities.c.name == old_name,
            )
            .values(name=new_name),
            update(semantic_relationship_fields)
            .where(
                semantic_relationship_fields.c.relationship_id.in_(_relationship_ids_of(model_id)),
                semantic_relationship_fields.c.entity_name == old_name,
            )
            .values(entity_name=new_name),
            update(semantic_nodes)
            .where(
                semantic_nodes.c.model_id == model_id,
                semantic_nodes.c.entity_name == old_name,
            )
            .values(entity_name=new_name),
        ]
        await self._write(statements, tracking)

    async def change_entity_table(
        self,
        model_id: UUID,
        name: str,
        table_id: UUID,
        tracking: Tracking,
    ) -> None:
        """Points an entity at another catalog table in the view."""
        statement = (
            update(semantic_entities)
            .where(
                semantic_entities.c.model_id == model_id,
                semantic_entities.c.name == name,
            )
            .values(table_id=table_id)
        )
        await self._write([statement], tracking)

    async def remove_entity(self, model_id: UUID, name: str, tracking: Tracking) -> None:
        """Removes an entity, its relationships and the nodes that mention it.

        The relationship ids are read first: deleting the relationship rows would
        otherwise empty the subquery that the field rows depend on.
        """
        async with self.transaction() as conn:
            referencing = [
                row.relationship_id
                for row in (await conn.execute(_referencing_relationship_ids(model_id, name))).all()
            ]
            if referencing:
                await conn.execute(
                    delete(semantic_relationship_fields).where(
                        semantic_relationship_fields.c.relationship_id.in_(referencing)
                    )
                )
                await conn.execute(
                    delete(semantic_relationships).where(
                        semantic_relationships.c.relationship_id.in_(referencing)
                    )
                )
            await conn.execute(
                delete(semantic_nodes).where(
                    semantic_nodes.c.model_id == model_id,
                    semantic_nodes.c.entity_name == name,
                )
            )
            await conn.execute(
                delete(semantic_entities).where(
                    semantic_entities.c.model_id == model_id,
                    semantic_entities.c.name == name,
                )
            )
            await self.insert_tracking_in_transaction(conn, tracking)

    async def get_entity(self, model_id: UUID, name: str) -> EntityRow | None:
        """Returns one entity, or ``None``."""
        row = await self._fetch_one(
            select(semantic_entities).where(
                semantic_entities.c.model_id == model_id,
                semantic_entities.c.name == name,
            )
        )
        return None if row is None else self._entity_row(row)

    async def get_entity_by_id(self, entity_id: UUID) -> EntityRow | None:
        """Returns one entity addressed by its identity, or ``None``."""
        row = await self._fetch_one(
            select(semantic_entities).where(semantic_entities.c.entity_id == entity_id)
        )
        if row is None:
            return None
        return self._entity_row(row)

    async def list_entities(self, model_id: UUID) -> list[EntityRow]:
        """Returns the entities of a model, ordered by name."""
        rows = await self._fetch_all(
            select(semantic_entities)
            .where(semantic_entities.c.model_id == model_id)
            .order_by(semantic_entities.c.name)
        )
        return [self._entity_row(row) for row in rows]

    # -- relationships ------------------------------------------------------

    async def register_relationship(
        self,
        relationship_id: UUID,
        model_id: UUID,
        from_refs: list[RefPair],
        to_refs: list[RefPair],
        cardinality: str,
        filter_direction: str,
        priority: int,
        tracking: Tracking,
    ) -> None:
        """Registers a relationship and its field references in the view."""
        statement = self._insert(semantic_relationships).values(
            relationship_id=relationship_id,
            model_id=model_id,
            cardinality=cardinality,
            filter_direction=filter_direction,
            priority=priority,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[semantic_relationships.c.relationship_id],
            set_={
                "model_id": statement.excluded.model_id,
                "cardinality": statement.excluded.cardinality,
                "filter_direction": statement.excluded.filter_direction,
                "priority": statement.excluded.priority,
            },
        )
        statements: list[Any] = [
            statement,
            delete(semantic_relationship_fields).where(
                semantic_relationship_fields.c.relationship_id == relationship_id
            ),
        ]
        statements.extend(self._field_inserts(relationship_id, "from", from_refs))
        statements.extend(self._field_inserts(relationship_id, "to", to_refs))
        await self._write(statements, tracking)

    async def change_relationship(
        self,
        relationship_id: UUID,
        from_refs: list[RefPair] | None,
        to_refs: list[RefPair] | None,
        cardinality: str | None,
        filter_direction: str | None,
        priority: int | None,
        tracking: Tracking,
    ) -> None:
        """Changes a relationship, rewriting the given sides only."""
        values: dict[str, Any] = {}
        if cardinality is not None:
            values["cardinality"] = cardinality
        if filter_direction is not None:
            values["filter_direction"] = filter_direction
        if priority is not None:
            values["priority"] = priority
        statements: list[Any] = []
        if values:
            statements.append(
                update(semantic_relationships)
                .where(semantic_relationships.c.relationship_id == relationship_id)
                .values(**values)
            )
        for side, refs in (("from", from_refs), ("to", to_refs)):
            if refs is None:
                continue
            statements.append(
                delete(semantic_relationship_fields).where(
                    semantic_relationship_fields.c.relationship_id == relationship_id,
                    semantic_relationship_fields.c.side == side,
                )
            )
            statements.extend(self._field_inserts(relationship_id, side, refs))
        await self._write(statements, tracking)

    async def remove_relationship(self, relationship_id: UUID, tracking: Tracking) -> None:
        """Removes a relationship and its field references in the view."""
        statements = [
            delete(semantic_relationship_fields).where(
                semantic_relationship_fields.c.relationship_id == relationship_id
            ),
            delete(semantic_relationships).where(
                semantic_relationships.c.relationship_id == relationship_id
            ),
        ]
        await self._write(statements, tracking)

    async def get_relationship(self, relationship_id: UUID) -> RelationshipRow | None:
        """Returns one relationship with its references, or ``None``."""
        row = await self._fetch_one(
            select(semantic_relationships).where(
                semantic_relationships.c.relationship_id == relationship_id
            )
        )
        if row is None:
            return None
        fields = await self._fetch_all(
            select(semantic_relationship_fields)
            .where(semantic_relationship_fields.c.relationship_id == relationship_id)
            .order_by(
                semantic_relationship_fields.c.side,
                semantic_relationship_fields.c.position,
            )
        )
        return self._relationship_row(row, fields)

    async def list_relationships(self, model_id: UUID) -> list[RelationshipRow]:
        """Returns the relationships of a model with their references."""
        rows = await self._fetch_all(
            select(semantic_relationships)
            .where(semantic_relationships.c.model_id == model_id)
            .order_by(
                semantic_relationships.c.priority,
                semantic_relationships.c.relationship_id,
            )
        )
        if not rows:
            return []
        fields = await self._fetch_all(
            select(semantic_relationship_fields)
            .where(
                semantic_relationship_fields.c.relationship_id.in_(_relationship_ids_of(model_id))
            )
            .order_by(
                semantic_relationship_fields.c.relationship_id,
                semantic_relationship_fields.c.side,
                semantic_relationship_fields.c.position,
            )
        )
        grouped: dict[UUID, list[Any]] = {}
        for field_row in fields:
            grouped.setdefault(as_uuid(field_row.relationship_id), []).append(field_row)
        return [
            self._relationship_row(row, grouped.get(as_uuid(row.relationship_id), []))
            for row in rows
        ]

    # -- diagrams -----------------------------------------------------------

    async def register_diagram(
        self,
        model_id: UUID,
        name: str,
        order: int,
        tracking: Tracking,
    ) -> None:
        """Registers a diagram in the view."""
        await self._write([self._diagram_upsert(model_id, name, order)], tracking)

    async def rename_diagram(
        self,
        model_id: UUID,
        old_name: str,
        new_name: str,
        tracking: Tracking,
    ) -> None:
        """Renames a diagram and the nodes it owns."""
        statements = [
            update(semantic_diagrams)
            .where(
                semantic_diagrams.c.model_id == model_id,
                semantic_diagrams.c.name == old_name,
            )
            .values(name=new_name),
            update(semantic_nodes)
            .where(
                semantic_nodes.c.model_id == model_id,
                semantic_nodes.c.diagram_name == old_name,
            )
            .values(diagram_name=new_name),
        ]
        await self._write(statements, tracking)

    async def change_diagram_order(
        self,
        model_id: UUID,
        name: str,
        order: int,
        tracking: Tracking,
    ) -> None:
        """Changes the sort hint of a diagram."""
        statement = (
            update(semantic_diagrams)
            .where(
                semantic_diagrams.c.model_id == model_id,
                semantic_diagrams.c.name == name,
            )
            .values(order=order)
        )
        await self._write([statement], tracking)

    async def remove_diagram(self, model_id: UUID, name: str, tracking: Tracking) -> None:
        """Removes a diagram and its nodes."""
        statements = [
            delete(semantic_nodes).where(
                semantic_nodes.c.model_id == model_id,
                semantic_nodes.c.diagram_name == name,
            ),
            delete(semantic_diagrams).where(
                semantic_diagrams.c.model_id == model_id,
                semantic_diagrams.c.name == name,
            ),
        ]
        await self._write(statements, tracking)

    async def get_diagram(self, model_id: UUID, name: str) -> DiagramRow | None:
        """Returns one diagram, or ``None``."""
        row = await self._fetch_one(
            select(semantic_diagrams).where(
                semantic_diagrams.c.model_id == model_id,
                semantic_diagrams.c.name == name,
            )
        )
        return None if row is None else self._diagram_row(row)

    async def list_diagrams(self, model_id: UUID) -> list[DiagramRow]:
        """Returns the diagrams of a model, ordered by sort hint and name."""
        rows = await self._fetch_all(
            select(semantic_diagrams)
            .where(semantic_diagrams.c.model_id == model_id)
            .order_by(semantic_diagrams.c.order, semantic_diagrams.c.name)
        )
        return [self._diagram_row(row) for row in rows]

    # -- nodes --------------------------------------------------------------

    async def place_node(
        self,
        model_id: UUID,
        diagram_name: str,
        entity_name: str,
        x: float,
        y: float,
        tracking: Tracking,
    ) -> None:
        """Places an entity on a diagram in the view."""
        await self._write(
            [self._node_upsert(model_id, diagram_name, entity_name, x, y)],
            tracking,
        )

    async def move_node(
        self,
        model_id: UUID,
        diagram_name: str,
        entity_name: str,
        x: float,
        y: float,
        tracking: Tracking,
    ) -> None:
        """Moves a placed entity on a diagram in the view."""
        statement = (
            update(semantic_nodes)
            .where(
                semantic_nodes.c.model_id == model_id,
                semantic_nodes.c.diagram_name == diagram_name,
                semantic_nodes.c.entity_name == entity_name,
            )
            .values(x=x, y=y)
        )
        await self._write([statement], tracking)

    async def remove_node(
        self,
        model_id: UUID,
        diagram_name: str,
        entity_name: str,
        tracking: Tracking,
    ) -> None:
        """Removes an entity from a diagram in the view."""
        statement = delete(semantic_nodes).where(
            semantic_nodes.c.model_id == model_id,
            semantic_nodes.c.diagram_name == diagram_name,
            semantic_nodes.c.entity_name == entity_name,
        )
        await self._write([statement], tracking)

    async def list_nodes(self, model_id: UUID, diagram_name: str) -> list[NodeRow]:
        """Returns the nodes of a diagram, ordered by entity name."""
        rows = await self._fetch_all(
            select(semantic_nodes)
            .where(
                semantic_nodes.c.model_id == model_id,
                semantic_nodes.c.diagram_name == diagram_name,
            )
            .order_by(semantic_nodes.c.entity_name)
        )
        return [self._node_row(row) for row in rows]

    # -- helpers ------------------------------------------------------------

    def _diagram_upsert(self, model_id: UUID, name: str, order: int) -> Any:
        """Returns the upsert of a diagram row."""
        statement = self._insert(semantic_diagrams).values(
            model_id=model_id,
            name=name,
            order=order,
        )
        return statement.on_conflict_do_update(
            index_elements=[semantic_diagrams.c.model_id, semantic_diagrams.c.name],
            set_={"order": statement.excluded.order},
        )

    def _node_upsert(
        self,
        model_id: UUID,
        diagram_name: str,
        entity_name: str,
        x: float,
        y: float,
    ) -> Any:
        """Returns the upsert of a node row."""
        statement = self._insert(semantic_nodes).values(
            model_id=model_id,
            diagram_name=diagram_name,
            entity_name=entity_name,
            x=x,
            y=y,
        )
        return statement.on_conflict_do_update(
            index_elements=[
                semantic_nodes.c.model_id,
                semantic_nodes.c.diagram_name,
                semantic_nodes.c.entity_name,
            ],
            set_={"x": statement.excluded.x, "y": statement.excluded.y},
        )

    def _field_inserts(
        self,
        relationship_id: UUID,
        side: str,
        refs: Sequence[RefPair],
    ) -> list[Any]:
        """Returns the inserts that rewrite one side of a relationship."""
        return [
            semantic_relationship_fields.insert().values(
                relationship_id=relationship_id,
                side=side,
                position=position,
                entity_name=entity_name,
                field_name=field_name,
            )
            for position, (entity_name, field_name) in enumerate(refs)
        ]

    # -- row builders -------------------------------------------------------

    @staticmethod
    def _model_row(row: Any) -> ModelRow:
        """Builds a model row from a database row."""
        return ModelRow(
            model_id=as_uuid(row.model_id),
            name=str(row.name),
            description=str(row.description),
        )

    @staticmethod
    def _entity_row(row: Any) -> EntityRow:
        """Builds an entity row from a database row."""
        return EntityRow(
            model_id=as_uuid(row.model_id),
            entity_id=as_uuid(row.entity_id),
            name=str(row.name),
            table_id=as_uuid(row.table_id),
        )

    @staticmethod
    def _diagram_row(row: Any) -> DiagramRow:
        """Builds a diagram row from a database row."""
        return DiagramRow(
            model_id=as_uuid(row.model_id),
            name=str(row.name),
            order=int(row.order),
        )

    @staticmethod
    def _node_row(row: Any) -> NodeRow:
        """Builds a node row from a database row."""
        return NodeRow(
            model_id=as_uuid(row.model_id),
            diagram_name=str(row.diagram_name),
            entity_name=str(row.entity_name),
            x=float(row.x),
            y=float(row.y),
        )

    @staticmethod
    def _relationship_row(row: Any, fields: Sequence[Any]) -> RelationshipRow:
        """Builds a relationship row from a database row and its field rows."""
        return RelationshipRow(
            relationship_id=as_uuid(row.relationship_id),
            model_id=as_uuid(row.model_id),
            from_refs=[
                (str(field.entity_name), str(field.field_name))
                for field in fields
                if str(field.side) == "from"
            ],
            to_refs=[
                (str(field.entity_name), str(field.field_name))
                for field in fields
                if str(field.side) == "to"
            ],
            cardinality=str(row.cardinality),
            filter_direction=str(row.filter_direction),
            priority=int(row.priority),
        )
