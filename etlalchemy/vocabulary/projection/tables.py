"""SQLAlchemy Core table definitions for the vocabulary read model.

The metadata is backend-agnostic: the async view compiles these tables with the
dialect of the configured datastore. No engine or session is created here.
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    Uuid,
)

metadata = MetaData()

vocabulary_domains = Table(
    "vocabulary_domains",
    metadata,
    Column("domain_id", Uuid(as_uuid=True), primary_key=True),
    Column("name", String, nullable=False),
    Column("description", String, nullable=False, server_default=""),
    Column("discarded_at", DateTime(timezone=True), nullable=True),
)

vocabulary_terms = Table(
    "vocabulary_terms",
    metadata,
    Column("term_id", Uuid(as_uuid=True), primary_key=True),
    Column("domain_id", Uuid(as_uuid=True), nullable=False),
    Column("parent_id", Uuid(as_uuid=True), nullable=True),
    Column("path", String, nullable=False),
    Column("name", String, nullable=False),
    Column("definition", Text, nullable=False),
    Column("status", String, nullable=False),
    Column("color", String, nullable=False, server_default=""),
    Column("discarded_at", DateTime(timezone=True), nullable=True),
)

vocabulary_term_aliases = Table(
    "vocabulary_term_aliases",
    metadata,
    Column("term_id", Uuid(as_uuid=True), nullable=False),
    Column("alias", String, nullable=False),
    PrimaryKeyConstraint("term_id", "alias"),
)

vocabulary_term_links = Table(
    "vocabulary_term_links",
    metadata,
    Column("term_id", Uuid(as_uuid=True), nullable=False),
    Column("target_id", Uuid(as_uuid=True), nullable=False),
    Column("target_kind", String, nullable=False),
    Column("field_name", String, nullable=False, server_default=""),
    PrimaryKeyConstraint("term_id", "target_id", "target_kind", "field_name"),
)

Index("vocabulary_terms_domain_id", vocabulary_terms.c.domain_id)
Index("vocabulary_terms_parent_id", vocabulary_terms.c.parent_id)
Index("vocabulary_terms_status", vocabulary_terms.c.status)
Index(
    "vocabulary_terms_domain_path",
    vocabulary_terms.c.domain_id,
    vocabulary_terms.c.path,
    unique=True,
    sqlite_where=vocabulary_terms.c.discarded_at.is_(None),
    postgresql_where=vocabulary_terms.c.discarded_at.is_(None),
)
Index(
    "vocabulary_term_links_target",
    vocabulary_term_links.c.target_id,
    vocabulary_term_links.c.target_kind,
)
