"""SQLAlchemy Core table definitions for the ingestion read model.

The metadata is backend-agnostic: the SQLite and PostgreSQL views compile these
tables with their own dialect (and, for PostgreSQL, with a schema-qualified copy).
No engine or session is created here.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    Uuid,
)

metadata = MetaData()

ingestion_connections = Table(
    "ingestion_connections",
    metadata,
    Column("connection_id", Uuid(as_uuid=True), primary_key=True),
    Column("name", String, nullable=False),
    Column("kind", String, nullable=False),
    Column("endpoint", String, nullable=False),
    Column("credential_ref", String, nullable=True),
    Column("has_inline_credential", Boolean, nullable=False),
    Column("default_catalog", String, nullable=True),
    Column("options", Text, nullable=False, server_default="{}"),
    Column("discarded_at", DateTime(timezone=True), nullable=True),
)

ingestion_import_runs = Table(
    "ingestion_import_runs",
    metadata,
    Column("run_id", Uuid(as_uuid=True), primary_key=True),
    Column("connection_id", Uuid(as_uuid=True), nullable=False),
    Column("target_catalog_id", Uuid(as_uuid=True), nullable=False),
    Column("source_catalog", String, nullable=True),
    Column("include_schemas", Text, nullable=False, server_default="[]"),
    Column("include_tables", Text, nullable=False, server_default="{}"),
    Column("schema_mapping", Text, nullable=False, server_default="{}"),
    Column("status", String, nullable=False),
    Column("schema_count", Integer, nullable=False),
    Column("table_count", Integer, nullable=False),
    Column("field_count", Integer, nullable=False),
    Column("error", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

Index("ingestion_import_runs_connection_id", ingestion_import_runs.c.connection_id)
Index("ingestion_import_runs_created_at", ingestion_import_runs.c.created_at)
