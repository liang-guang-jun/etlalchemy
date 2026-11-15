"""SQLAlchemy Core table definitions for the catalog read model.

The metadata is backend-agnostic: the SQLite and PostgreSQL views compile these
tables with their own dialect (and, for PostgreSQL, with a schema-qualified copy).
No engine or session is created here.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Uuid,
)

metadata = MetaData()

catalogs = Table(
    "catalog_catalogs",
    metadata,
    Column("catalog_id", Uuid(as_uuid=True), primary_key=True),
    Column("name", String, nullable=False),
    Column("description", String, nullable=False, server_default=""),
    Column("discarded_at", DateTime(timezone=True), nullable=True),
)

catalog_schemas = Table(
    "catalog_schemas",
    metadata,
    Column("schema_id", Uuid(as_uuid=True), primary_key=True),
    Column("catalog_id", Uuid(as_uuid=True), nullable=False),
    Column("name", String, nullable=False),
    Column("description", String, nullable=False, server_default=""),
    Column("discarded_at", DateTime(timezone=True), nullable=True),
)

catalog_tables = Table(
    "catalog_tables",
    metadata,
    Column("table_id", Uuid(as_uuid=True), primary_key=True),
    Column("schema_id", Uuid(as_uuid=True), nullable=False),
    Column("catalog_id", Uuid(as_uuid=True), nullable=False),
    Column("name", String, nullable=False),
    Column("description", String, nullable=False, server_default=""),
    Column("discarded_at", DateTime(timezone=True), nullable=True),
)

catalog_fields = Table(
    "catalog_fields",
    metadata,
    Column("table_id", Uuid(as_uuid=True), nullable=False),
    Column("field_id", Uuid(as_uuid=True), nullable=False),
    Column("name", String, nullable=False),
    Column("data_type", String, nullable=False),
    Column("nullable", Boolean, nullable=False),
    Column("comment", String, nullable=False, server_default=""),
    PrimaryKeyConstraint("table_id", "name"),
)

Index("catalog_tables_schema_id", catalog_tables.c.schema_id)
Index("catalog_fields_table_id", catalog_fields.c.table_id)
