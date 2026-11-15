"""SQLAlchemy Core table definitions for the LLM provider read model.

The metadata is backend-agnostic: the SQLite and PostgreSQL views compile these
tables with their own dialect. No engine or session is created here.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    MetaData,
    String,
    Table,
    Text,
    Uuid,
)

metadata = MetaData()

llm_config_providers = Table(
    "llm_config_providers",
    metadata,
    Column("provider_id", Uuid(as_uuid=True), primary_key=True),
    Column("name", String, nullable=False),
    Column("kind", String, nullable=False),
    Column("endpoint", String, nullable=True),
    Column("credential_ref", String, nullable=True),
    Column("has_inline_credential", Boolean, nullable=False),
    Column("default_model", String, nullable=False),
    Column("options", Text, nullable=False, server_default="{}"),
    Column("owner_user_id", Uuid(as_uuid=True), nullable=False),
    Column("tenant_id", Uuid(as_uuid=True), nullable=True),
    Column("is_public", Boolean, nullable=False),
    Column("is_system_default", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("discarded_at", DateTime(timezone=True), nullable=True),
)

llm_config_provider_shares = Table(
    "llm_config_provider_shares",
    metadata,
    Column("provider_id", Uuid(as_uuid=True), primary_key=True),
    Column("scope", String, primary_key=True),
    Column("target_id", Uuid(as_uuid=True), primary_key=True),
)

llm_config_provider_defaults = Table(
    "llm_config_provider_defaults",
    metadata,
    Column("provider_id", Uuid(as_uuid=True), primary_key=True),
    Column("scope", String, primary_key=True),
    Column("target_id", Uuid(as_uuid=True), primary_key=True),
)

Index("llm_config_providers_owner", llm_config_providers.c.owner_user_id)
Index("llm_config_providers_name", llm_config_providers.c.name)
Index("llm_config_provider_shares_target", llm_config_provider_shares.c.target_id)
Index("llm_config_provider_defaults_target", llm_config_provider_defaults.c.target_id)
