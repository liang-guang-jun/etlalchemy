"""SQLAlchemy Core table definitions for the comment read model.

The metadata is backend-agnostic: the async view compiles these tables with the
dialect of the configured datastore. Mention lists are stored as JSON text, as
the ingestion read model does, so SQLite and PostgreSQL share one definition.
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    Uuid,
)

metadata = MetaData()

comment_threads = Table(
    "comment_threads",
    metadata,
    Column("thread_id", Uuid(as_uuid=True), primary_key=True),
    Column("target_type", String, nullable=False),
    Column("target_id", Uuid(as_uuid=True), nullable=False),
    Column("title", String, nullable=False, server_default=""),
    Column("status", String, nullable=False),
    Column("author_user_id", Uuid(as_uuid=True), nullable=False),
    Column("author_tenant_id", Uuid(as_uuid=True), nullable=True),
    Column("comment_count", Integer, nullable=False, server_default="0"),
    Column("last_activity_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("resolved_at", DateTime(timezone=True), nullable=True),
    Column("resolved_by", Uuid(as_uuid=True), nullable=True),
    Column("discarded_at", DateTime(timezone=True), nullable=True),
)

comment_comments = Table(
    "comment_comments",
    metadata,
    Column("comment_id", Uuid(as_uuid=True), primary_key=True),
    Column("thread_id", Uuid(as_uuid=True), nullable=False),
    Column("parent_comment_id", Uuid(as_uuid=True), nullable=True),
    Column("author_user_id", Uuid(as_uuid=True), nullable=False),
    Column("author_tenant_id", Uuid(as_uuid=True), nullable=True),
    Column("body", Text, nullable=False),
    Column("mentions", Text, nullable=False, server_default="[]"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("edited_at", DateTime(timezone=True), nullable=True),
    Column("discarded_at", DateTime(timezone=True), nullable=True),
)

comment_mentions = Table(
    "comment_mentions",
    metadata,
    Column("comment_id", Uuid(as_uuid=True), nullable=False),
    Column("thread_id", Uuid(as_uuid=True), nullable=False),
    Column("user_id", Uuid(as_uuid=True), nullable=False),
    Column("author_user_id", Uuid(as_uuid=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("comment_id", "user_id"),
)

Index("comment_threads_target", comment_threads.c.target_type, comment_threads.c.target_id)
Index("comment_threads_status", comment_threads.c.status)
Index("comment_threads_author", comment_threads.c.author_user_id)
Index("comment_threads_created", comment_threads.c.created_at)
Index(
    "comment_comments_thread",
    comment_comments.c.thread_id,
    comment_comments.c.created_at,
)
Index("comment_comments_parent", comment_comments.c.parent_comment_id)
Index("comment_mentions_user", comment_mentions.c.user_id, comment_mentions.c.created_at)
