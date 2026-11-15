"""SQLAlchemy Core table definitions for the IAM read model.

The metadata is backend-agnostic: the async view compiles these tables with the
dialect of the configured datastore. Structured values are stored as JSON text so
SQLite and PostgreSQL behave identically. No engine or session is created here.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
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

iam_tenants = Table(
    "iam_tenants",
    metadata,
    Column("tenant_id", Uuid(as_uuid=True), primary_key=True),
    Column("name", String, nullable=False),
    Column("description", Text, nullable=False, server_default=""),
    Column("status", String, nullable=False),
    Column("discarded_at", DateTime(timezone=True), nullable=True),
)

iam_users = Table(
    "iam_users",
    metadata,
    Column("user_id", Uuid(as_uuid=True), primary_key=True),
    Column("username", String, nullable=False),
    Column("email", String, nullable=False),
    Column("display_name", Text, nullable=False, server_default=""),
    Column("status", String, nullable=False),
    Column("is_system_admin", Boolean, nullable=False, server_default="0"),
    Column("discarded_at", DateTime(timezone=True), nullable=True),
)

iam_tenant_members = Table(
    "iam_tenant_members",
    metadata,
    Column("tenant_id", Uuid(as_uuid=True), nullable=False),
    Column("user_id", Uuid(as_uuid=True), nullable=False),
    Column("joined_at", DateTime(timezone=True), nullable=False),
    Column("status", String, nullable=False),
    PrimaryKeyConstraint("tenant_id", "user_id"),
)

iam_identities = Table(
    "iam_identities",
    metadata,
    Column("identity_id", Uuid(as_uuid=True), primary_key=True),
    Column("user_id", Uuid(as_uuid=True), nullable=False),
    Column("identity_type", String, nullable=False),
    Column("provider", String, nullable=False),
    Column("display_name", Text, nullable=False, server_default=""),
    Column("status", String, nullable=False),
    Column("credential_version", Integer, nullable=False, server_default="0"),
    Column("provider_id", Uuid(as_uuid=True), nullable=True),
    Column("oidc_issuer", String, nullable=True),
    Column("oidc_subject", String, nullable=True),
    Column("last_used_at", DateTime(timezone=True), nullable=True),
    Column("discarded_at", DateTime(timezone=True), nullable=True),
)

iam_password_creds = Table(
    "iam_password_creds",
    metadata,
    Column("identity_id", Uuid(as_uuid=True), primary_key=True),
    Column("password_hash", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

iam_oidc_creds = Table(
    "iam_oidc_creds",
    metadata,
    Column("identity_id", Uuid(as_uuid=True), primary_key=True),
    Column("provider_id", Uuid(as_uuid=True), nullable=False),
    Column("issuer", String, nullable=False),
    Column("subject", String, nullable=False),
)

iam_api_keys = Table(
    "iam_api_keys",
    metadata,
    Column("key_id", Uuid(as_uuid=True), primary_key=True),
    Column("identity_id", Uuid(as_uuid=True), nullable=False),
    Column("user_id", Uuid(as_uuid=True), nullable=False),
    Column("prefix", String, nullable=False),
    Column("secret_hash", Text, nullable=False),
    Column("scopes", JSON, nullable=False),
    Column("status", String, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    Column("grace_until", DateTime(timezone=True), nullable=True),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Column("rotated_from", Uuid(as_uuid=True), nullable=True),
    Column("last_used_at", DateTime(timezone=True), nullable=True),
)

iam_sessions = Table(
    "iam_sessions",
    metadata,
    Column("session_id", Uuid(as_uuid=True), primary_key=True),
    Column("identity_id", Uuid(as_uuid=True), nullable=False),
    Column("user_id", Uuid(as_uuid=True), nullable=False),
    Column("tenant_id", Uuid(as_uuid=True), nullable=True),
    Column("identity_type", String, nullable=False),
    Column("api_key_id", Uuid(as_uuid=True), nullable=True),
    Column("credential_version", Integer, nullable=False),
    Column("status", String, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("revoked_reason", String, nullable=True),
)

iam_groups = Table(
    "iam_groups",
    metadata,
    Column("group_id", Uuid(as_uuid=True), primary_key=True),
    Column("tenant_id", Uuid(as_uuid=True), nullable=False),
    Column("name", String, nullable=False),
    Column("description", Text, nullable=False, server_default=""),
    Column("parent_group_id", Uuid(as_uuid=True), nullable=True),
    Column("discarded_at", DateTime(timezone=True), nullable=True),
)

iam_group_members = Table(
    "iam_group_members",
    metadata,
    Column("group_id", Uuid(as_uuid=True), nullable=False),
    Column("member_id", Uuid(as_uuid=True), nullable=False),
    Column("member_kind", String, nullable=False),
    Column("added_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("group_id", "member_id", "member_kind"),
)

iam_permission_grants = Table(
    "iam_permission_grants",
    metadata,
    Column("group_id", Uuid(as_uuid=True), nullable=False),
    Column("tenant_id", Uuid(as_uuid=True), nullable=False),
    Column("object", String, nullable=False),
    Column("action", String, nullable=False),
    PrimaryKeyConstraint("group_id", "tenant_id", "object", "action"),
)

iam_auth_providers = Table(
    "iam_auth_providers",
    metadata,
    Column("provider_id", Uuid(as_uuid=True), primary_key=True),
    Column("provider_key", String, nullable=False),
    Column("kind", String, nullable=False),
    Column("display_name", Text, nullable=False),
    Column("tenant_id", Uuid(as_uuid=True), nullable=True),
    Column("config", JSON, nullable=False),
    Column("status", String, nullable=False),
    Column("discarded_at", DateTime(timezone=True), nullable=True),
)

iam_casbin_rules = Table(
    "iam_casbin_rules",
    metadata,
    Column("ptype", String, nullable=False),
    Column("v0", String, nullable=False),
    Column("v1", String, nullable=False),
    Column("v2", String, nullable=False),
    Column("v3", String, nullable=False, server_default=""),
    PrimaryKeyConstraint("ptype", "v0", "v1", "v2", "v3"),
)

iam_audit_log = Table(
    "iam_audit_log",
    metadata,
    Column("audit_id", Integer, primary_key=True, autoincrement=True),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("actor_user_id", Uuid(as_uuid=True), nullable=True),
    Column("actor_identity_id", Uuid(as_uuid=True), nullable=True),
    Column("action", String, nullable=False),
    Column("target_type", String, nullable=False),
    Column("target_id", String, nullable=False),
    Column("tenant_id", Uuid(as_uuid=True), nullable=True),
    Column("result", String, nullable=False),
    Column("detail", JSON, nullable=False),
)

Index("iam_users_username", iam_users.c.username)
Index("iam_users_email", iam_users.c.email)
Index("iam_identities_user_id", iam_identities.c.user_id)
Index("iam_identities_oidc", iam_identities.c.oidc_issuer, iam_identities.c.oidc_subject)
Index("iam_api_keys_prefix", iam_api_keys.c.prefix)
Index("iam_api_keys_user", iam_api_keys.c.user_id)
Index("iam_sessions_identity", iam_sessions.c.identity_id, iam_sessions.c.status)
Index("iam_sessions_user_tenant", iam_sessions.c.user_id, iam_sessions.c.tenant_id)
Index("iam_sessions_api_key", iam_sessions.c.api_key_id)
Index("iam_groups_tenant", iam_groups.c.tenant_id)
Index("iam_group_members_member", iam_group_members.c.member_id, iam_group_members.c.member_kind)
Index("iam_permission_grants_tenant", iam_permission_grants.c.tenant_id)
Index("iam_auth_providers_key", iam_auth_providers.c.provider_key)
Index("iam_casbin_rules_subject", iam_casbin_rules.c.ptype, iam_casbin_rules.c.v0)
Index("iam_audit_log_occurred", iam_audit_log.c.occurred_at)
