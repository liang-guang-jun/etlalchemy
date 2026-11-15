"""SQLAlchemy Core table definitions for the semantic read model.

The metadata is backend-agnostic: the async view compiles these tables with the
dialect of the configured datastore. No engine or session is created here.
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Uuid,
)

metadata = MetaData()

semantic_models = Table(
    "semantic_models",
    metadata,
    Column("model_id", Uuid(as_uuid=True), primary_key=True),
    Column("name", String, nullable=False),
    Column("description", String, nullable=False, server_default=""),
    Column("discarded_at", DateTime(timezone=True), nullable=True),
)

semantic_entities = Table(
    "semantic_entities",
    metadata,
    Column("model_id", Uuid(as_uuid=True), nullable=False),
    Column("entity_id", Uuid(as_uuid=True), nullable=False),
    Column("name", String, nullable=False),
    Column("table_id", Uuid(as_uuid=True), nullable=False),
    PrimaryKeyConstraint("model_id", "name"),
)

semantic_relationships = Table(
    "semantic_relationships",
    metadata,
    Column("relationship_id", Uuid(as_uuid=True), primary_key=True),
    Column("model_id", Uuid(as_uuid=True), nullable=False),
    Column("cardinality", String, nullable=False),
    Column("filter_direction", String, nullable=False),
    Column("priority", Integer, nullable=False, server_default="0"),
)

semantic_relationship_fields = Table(
    "semantic_relationship_fields",
    metadata,
    Column("relationship_id", Uuid(as_uuid=True), nullable=False),
    Column("side", String, nullable=False),
    Column("position", Integer, nullable=False),
    Column("entity_name", String, nullable=False),
    Column("field_name", String, nullable=False),
    PrimaryKeyConstraint("relationship_id", "side", "position"),
)

semantic_diagrams = Table(
    "semantic_diagrams",
    metadata,
    Column("model_id", Uuid(as_uuid=True), nullable=False),
    Column("name", String, nullable=False),
    Column("order", Integer, nullable=False, server_default="0"),
    PrimaryKeyConstraint("model_id", "name"),
)

semantic_nodes = Table(
    "semantic_nodes",
    metadata,
    Column("model_id", Uuid(as_uuid=True), nullable=False),
    Column("diagram_name", String, nullable=False),
    Column("entity_name", String, nullable=False),
    Column("x", Float, nullable=False),
    Column("y", Float, nullable=False),
    PrimaryKeyConstraint("model_id", "diagram_name", "entity_name"),
)

Index("semantic_models_name", semantic_models.c.name)
Index("semantic_entities_table_id", semantic_entities.c.table_id)
Index("semantic_relationships_model_id", semantic_relationships.c.model_id)
Index("semantic_relationship_fields_entity", semantic_relationship_fields.c.entity_name)
Index("semantic_nodes_entity", semantic_nodes.c.entity_name)
