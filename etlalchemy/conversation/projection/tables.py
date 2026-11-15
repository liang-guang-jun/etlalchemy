"""SQLAlchemy Core table definitions for the conversation read model.

The metadata is backend-agnostic: the SQLite and PostgreSQL views compile these
tables with their own dialect. No engine or session is created here.
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

conversation_conversations = Table(
    "conversation_conversations",
    metadata,
    Column("conversation_id", Uuid(as_uuid=True), primary_key=True),
    Column("user_id", Uuid(as_uuid=True), nullable=False),
    Column("tenant_id", Uuid(as_uuid=True), nullable=True),
    Column("title", String, nullable=False, server_default=""),
    Column("status", String, nullable=False),
    Column("active_llm_provider_id", Uuid(as_uuid=True), nullable=True),
    Column("message_count", Integer, nullable=False, server_default="0"),
    Column("run_count", Integer, nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_activity_at", DateTime(timezone=True), nullable=False),
    Column("discarded_at", DateTime(timezone=True), nullable=True),
)

conversation_messages = Table(
    "conversation_messages",
    metadata,
    Column("message_id", Uuid(as_uuid=True), primary_key=True),
    Column("conversation_id", Uuid(as_uuid=True), nullable=False),
    Column("role", String, nullable=False),
    Column("content", Text, nullable=False),
    Column("interrupted", Boolean, nullable=False, server_default="0"),
    Column("input_tokens", Integer, nullable=False, server_default="0"),
    Column("output_tokens", Integer, nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("reasoning", Text, nullable=False, server_default=""),
    Column("discarded_at", DateTime(timezone=True), nullable=True),
)

conversation_message_resources = Table(
    "conversation_message_resources",
    metadata,
    Column("message_id", Uuid(as_uuid=True), primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    Column("uri", Text, nullable=False),
    Column("size_bytes", Integer, nullable=False, server_default="0"),
    Column("mime_type", String, nullable=False, server_default=""),
    Column("read_at", DateTime(timezone=True), nullable=True),
)

conversation_message_tools = Table(
    "conversation_message_tools",
    metadata,
    Column("message_id", Uuid(as_uuid=True), primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    Column("tool", String, nullable=False),
    Column("args_hash", String, nullable=False, server_default=""),
    Column("status", String, nullable=False, server_default="ok"),
    Column("duration_ms", Integer, nullable=False, server_default="0"),
    Column("error_code", String, nullable=True),
    Column("args_json", Text, nullable=False, server_default=""),
    Column("result_preview", Text, nullable=False, server_default=""),
)

conversation_runs = Table(
    "conversation_runs",
    metadata,
    Column("run_id", Uuid(as_uuid=True), primary_key=True),
    Column("conversation_id", Uuid(as_uuid=True), nullable=False),
    Column("message_id", Uuid(as_uuid=True), nullable=False),
    Column("status", String, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("error", Text, nullable=True),
)

conversation_approvals = Table(
    "conversation_approvals",
    metadata,
    Column("approval_id", Uuid(as_uuid=True), primary_key=True),
    Column("run_id", Uuid(as_uuid=True), nullable=False),
    Column("conversation_id", Uuid(as_uuid=True), nullable=False),
    Column("tool", String, nullable=False),
    Column("args_hash", String, nullable=False, server_default=""),
    Column("reason", Text, nullable=False, server_default=""),
    Column("status", String, nullable=False),
    Column("requested_at", DateTime(timezone=True), nullable=False),
    Column("decided_by", Uuid(as_uuid=True), nullable=True),
    Column("decided_at", DateTime(timezone=True), nullable=True),
)

Index("conversation_conversations_user", conversation_conversations.c.user_id)
Index(
    "conversation_conversations_activity",
    conversation_conversations.c.last_activity_at,
)
Index("conversation_messages_conversation", conversation_messages.c.conversation_id)
Index("conversation_runs_conversation", conversation_runs.c.conversation_id)
Index("conversation_approvals_run", conversation_approvals.c.run_id)
