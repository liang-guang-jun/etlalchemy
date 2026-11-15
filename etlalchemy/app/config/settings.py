"""Settings models for the assembly layer."""

from __future__ import annotations

import base64
from typing import Literal
from urllib.parse import quote, urlparse

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from etlalchemy.agent.redaction import DEFAULT_REDACT_KEYS
from etlalchemy.comment.aggregates.types import DEFAULT_TARGET_TYPES
from etlalchemy.llm_config.aggregates.types import PROFILE_KINDS
from etlalchemy.shared.credentials import profile_reference

PERSISTENCE_MODULE = "eventsourcing.asyncio.sqlalchemy"
"""Persistence module of the asyncio infrastructure used by every context."""

SQLITE_ASYNC_DRIVER = "sqlite+aiosqlite"
"""SQLAlchemy async driver of the SQLite backend."""

POSTGRES_ASYNC_DRIVER = "postgresql+psycopg"
"""SQLAlchemy async driver of the PostgreSQL backend."""


def postgres_parts(dsn: str) -> tuple[str, str, str, str, str]:
    """Splits a PostgreSQL DSN into database, host, port, user and password."""
    parsed = urlparse(dsn)
    return (
        parsed.path.lstrip("/"),
        parsed.hostname or "localhost",
        str(parsed.port or 5432),
        parsed.username or "",
        parsed.password or "",
    )


class DatabaseSettings(BaseModel):
    """Database settings shared by the bounded contexts."""

    backend: Literal["sqlite", "postgres"] = "sqlite"
    sqlite_path: str = "./catalog.db"
    postgres_dsn: str = ""

    @model_validator(mode="after")
    def _validate_backend(self) -> DatabaseSettings:
        """Validates that the selected backend is fully configured."""
        if self.backend == "postgres":
            if not self.postgres_dsn.strip():
                msg = "postgres_dsn is required when backend is 'postgres'"
                raise ValueError(msg)
            if not self.postgres_dsn.startswith(("postgres://", "postgresql://")):
                msg = "postgres_dsn must be a postgres:// or postgresql:// URL"
                raise ValueError(msg)
        return self

    def to_sqlalchemy_url(self) -> str:
        """Returns the async SQLAlchemy URL of the selected backend."""
        if self.backend == "sqlite":
            return f"{SQLITE_ASYNC_DRIVER}:///{self.sqlite_path}"
        dbname, host, port, user, password = postgres_parts(self.postgres_dsn)
        credentials = f"{quote(user, safe='')}:{quote(password, safe='')}@" if user else ""
        return f"{POSTGRES_ASYNC_DRIVER}://{credentials}{host}:{port}/{dbname}"

    def to_eventsourcing_env(self) -> dict[str, str]:
        """Returns the environment expected by the asyncio eventsourcing factories."""
        return {
            "PERSISTENCE_MODULE": PERSISTENCE_MODULE,
            "SQLALCHEMY_URL": self.to_sqlalchemy_url(),
            "CREATE_TABLE": "y",
        }


class DatabaseOverride(BaseModel):
    """Field-level database overrides for one bounded context."""

    backend: Literal["sqlite", "postgres"] | None = None
    sqlite_path: str | None = None
    postgres_dsn: str | None = None

    def merge_onto(self, base: DatabaseSettings) -> DatabaseSettings:
        """Merges the non-``None`` fields onto the given base settings."""
        merged = base.model_dump()
        merged.update(self.model_dump(exclude_none=True))
        return DatabaseSettings(**merged)


class ProjectionSettings(BaseModel):
    """Settings of one context's projection runner."""

    enabled: bool = True
    tracking_table_name: str = "catalog_projection_tracking"


class CatalogSettings(BaseModel):
    """Settings of the catalog context."""

    database: DatabaseOverride | None = None
    projection: ProjectionSettings = Field(default_factory=ProjectionSettings)


class IngestionProjectionSettings(ProjectionSettings):
    """Projection settings of the ingestion context."""

    tracking_table_name: str = "ingestion_projection_tracking"


class SecretsSettings(BaseModel):
    """Settings of the credential resolver used by the ingestion context."""

    file_root: str | None = None
    """Optional root directory used to resolve relative ``file:`` references."""


class IngestionSettings(BaseModel):
    """Settings of the ingestion context."""

    database: DatabaseOverride | None = None
    projection: IngestionProjectionSettings = Field(default_factory=IngestionProjectionSettings)
    secrets: SecretsSettings = Field(default_factory=SecretsSettings)
    source_kinds: list[str] = Field(default_factory=lambda: ["databricks", "postgres"])


class VocabularyProjectionSettings(ProjectionSettings):
    """Projection settings of the vocabulary context."""

    tracking_table_name: str = "vocabulary_projection_tracking"


class VocabularySettings(BaseModel):
    """Settings of the vocabulary context."""

    database: DatabaseOverride | None = None
    projection: VocabularyProjectionSettings = Field(default_factory=VocabularyProjectionSettings)


class SemanticProjectionSettings(ProjectionSettings):
    """Projection settings of the semantic context."""

    tracking_table_name: str = "semantic_projection_tracking"


class SemanticSettings(BaseModel):
    """Settings of the semantic context."""

    database: DatabaseOverride | None = None
    projection: SemanticProjectionSettings = Field(default_factory=SemanticProjectionSettings)


class CommentProjectionSettings(ProjectionSettings):
    """Projection settings of the comment context."""

    tracking_table_name: str = "comment_projection_tracking"


class CommentSettings(BaseModel):
    """Settings of the comment context."""

    database: DatabaseOverride | None = None
    projection: CommentProjectionSettings = Field(default_factory=CommentProjectionSettings)
    max_body_length: int = 10_000
    """Maximum length of a comment body."""
    max_title_length: int = 200
    """Maximum length of a thread title."""
    max_mentions_per_comment: int = 20
    """Maximum number of users one comment may mention."""
    max_comments_per_thread: int = 10_000
    """Hard cap on the comments of one thread, including discarded ones."""
    soft_max_reply_depth: int = 0
    """Advisory reply depth; ``0`` disables the warning."""
    depth_warning_message: str = (
        "This reply is at depth {depth}, beyond the suggested {soft_max}; "
        "consider starting a new thread for a deeper discussion."
    )
    """Template of the advisory warning returned for a deep reply."""
    default_page_size: int = 50
    """Page size used when a read does not specify one."""
    max_page_size: int = 200
    """Upper bound of every page size."""
    validate_target_exists: bool = False
    """Whether a write checks that the target exists."""
    enforce_target_tenant: bool = False
    """Whether a write checks a target-scoped permission in IAM."""
    read_requires_session: bool = True
    """Whether reads require a session."""
    allow_multiple_threads: bool = True
    """Whether one target may have more than one live thread."""
    target_types: list[str] = Field(
        default_factory=lambda: sorted(DEFAULT_TARGET_TYPES),
    )
    """Target types accepted on the write path."""


class LlmConfigProjectionSettings(ProjectionSettings):
    """Projection settings of the LLM provider context."""

    tracking_table_name: str = "llm_config_projection_tracking"


class LlmConfigSettings(BaseModel):
    """Settings of the LLM provider context."""

    database: DatabaseOverride | None = None
    projection: LlmConfigProjectionSettings = Field(
        default_factory=LlmConfigProjectionSettings,
    )


class ConversationProjectionSettings(ProjectionSettings):
    """Projection settings of the conversation context."""

    tracking_table_name: str = "conversation_projection_tracking"


class ConversationSettings(BaseModel):
    """Settings of the conversation context."""

    database: DatabaseOverride | None = None
    projection: ConversationProjectionSettings = Field(
        default_factory=ConversationProjectionSettings,
    )
    max_message_chars: int = 262_144
    """Maximum number of characters of one message body."""
    max_content_chars: int = 65_536
    """Maximum number of characters of one tool or resource record payload."""
    default_page_size: int = 50
    """Page size used when a read does not specify one."""
    max_page_size: int = 200
    """Upper bound of every page size."""


class IamProjectionSettings(ProjectionSettings):
    """Projection settings of the IAM context."""

    tracking_table_name: str = "iam_projection_tracking"


class IamPolicySettings(BaseModel):
    """Settings of the Casbin policy cache."""

    reload_interval_seconds: float = 1.0
    """Age after which the in-memory policy is rebuilt from the read model."""


class IamSettings(BaseModel):
    """Settings of the IAM context."""

    database: DatabaseOverride | None = None
    projection: IamProjectionSettings = Field(default_factory=IamProjectionSettings)
    policy: IamPolicySettings = Field(default_factory=IamPolicySettings)
    password_min_length: int = 8
    """Minimum length of a new password."""
    max_api_keys: int = 20
    """Maximum number of live API keys per user."""
    api_key_grace_max_days: int = 30
    """Upper bound of an API key grace period."""
    max_group_depth: int = 64
    """Maximum length of a group ancestor chain."""
    password_session_minutes: int = 480
    """Session lifetime after a password login."""
    oidc_session_minutes: int = 480
    """Session lifetime after an OIDC login."""
    api_key_session_minutes: int = 60
    """Session lifetime after an API key login."""
    api_key_pepper: str | None = None
    """Pepper of the API key hashes; ``None`` keeps a plain SHA-256 digest."""
    secrets_file_root: str | None = None
    """Root directory used to resolve relative ``file:`` secret references."""
    record_denied_authorizations: bool = True
    """Whether a denied authorization is recorded in the audit log."""
    bearer_token_prefix: str = "iam_sess_"
    """Prefix of the bearer tokens the HTTP API and the MCP server accept."""
    session_refresh_lead_minutes: int = 5
    """How long before expiry a client should refresh its session."""

    @model_validator(mode="after")
    def _validate_session_refresh_lead(self) -> IamSettings:
        """Keeps the refresh lead positive and below every session lifetime.

        A lead that is not shorter than the session itself would make a client
        refresh in a loop, so the setting is rejected instead of clamped.

        Returns:
            The validated settings.

        Raises:
            ValueError: When the lead is not in ``[1, shortest lifetime)``.
        """
        shortest = min(
            self.password_session_minutes,
            self.oidc_session_minutes,
            self.api_key_session_minutes,
        )
        if not 1 <= self.session_refresh_lead_minutes < shortest:
            msg = (
                "session_refresh_lead_minutes must be at least 1 and below the "
                f"shortest session lifetime ({shortest} minutes)"
            )
            raise ValueError(msg)
        return self


LlmProviderKind = Literal["openai", "databricks_ai_gateway"]
"""LLM provider kinds the chat model factory can build."""

AgentAuthMode = Literal["service_account", "user_proxy"]
"""How the agent authenticates against the MCP endpoint."""

ApprovalDefault = Literal["deny", "allow"]
"""Decision used when no tool approval rule matches."""

ApprovalAction = Literal["auto", "require_approval", "deny"]
"""What the agent does with one tool call."""


class LlmBootstrapSettings(BaseModel):
    """The single LLM provider described by the configuration file.

    The named provider is created on startup when it is missing and synchronised
    (endpoint, model, options and credential) when it exists. Every other LLM
    provider lives in the database and is managed through the API.
    """

    name: str = "default"
    """Name of the bootstrapped provider."""
    kind: LlmProviderKind = "openai"
    """Provider kind the chat model factory builds."""
    endpoint: str | None = None
    """Base URL; required for ``databricks_ai_gateway``."""
    credential_ref: str | None = None
    """External secret reference, for example ``env:OPENAI_API_KEY``."""
    token: str | None = Field(default=None, repr=False)
    """Inline credential; encrypted at rest and therefore needs ``cipher_key``."""
    default_model: str = "gpt-4o-mini"
    """Model used when a request does not name one."""
    options: dict[str, str] = Field(default_factory=dict)
    """Extra model options such as ``temperature`` or ``max_tokens``."""

    @model_validator(mode="after")
    def _validate_provider(self) -> LlmBootstrapSettings:
        """Requires exactly one credential and an endpoint for Databricks.

        A ``profile:`` credential reference is only valid for the Databricks
        gateway, which then also supplies the workspace host.

        Returns:
            The validated settings.

        Raises:
            ValueError: When the credential or the endpoint is missing, or a
                profile reference targets another kind.
        """
        if (self.credential_ref is None) == (self.token is None):
            msg = "exactly one of credential_ref / token is required"
            raise ValueError(msg)
        profile = profile_reference(self.credential_ref)
        if profile is not None and self.kind not in PROFILE_KINDS:
            msg = "profile credentials are only supported by kind 'databricks_ai_gateway'"
            raise ValueError(msg)
        if (
            self.kind == "databricks_ai_gateway"
            and profile is None
            and not (self.endpoint or "").strip()
        ):
            msg = "endpoint is required when kind is 'databricks_ai_gateway'"
            raise ValueError(msg)
        return self


class AgentAuthSettings(BaseModel):
    """Settings of the agent's own credentials against the MCP endpoint."""

    mode: AgentAuthMode = "service_account"
    """``service_account`` exchanges an API key, ``user_proxy`` forwards a token."""
    credential_ref: str | None = None
    """Reference of the API key used by ``service_account`` mode."""
    tenant_id: str | None = None
    """Tenant the exchanged session acts in, or ``None`` for a tenant-free one."""


class AgentLimitsSettings(BaseModel):
    """Hard limits of one agent run."""

    max_tool_calls: int = 25
    """Maximum number of tool calls of one run."""
    max_wall_clock_seconds: int = 600
    """Maximum duration of one run."""
    tool_timeout_seconds: int = 60
    """Timeout of a single tool call."""
    max_tool_output_chars: int = 32_000
    """Maximum length of one tool result before it is truncated."""
    max_tool_args_chars: int = 2_000
    """Maximum length of the argument preview sent to the browser."""
    max_tool_result_preview_chars: int = 4_000
    """Maximum length of the result preview sent to the browser."""
    max_reasoning_chars: int = 16_000
    """Maximum length of the thinking kept with a message."""
    token_budget: int = 128_000
    """Token budget of one run."""


class AgentApprovalRule(BaseModel):
    """One tool approval rule."""

    match: str = "*"
    """Glob pattern matched against the tool name."""
    when: dict[str, str] = Field(default_factory=dict)
    """Conditions that must all hold, for example ``{"tenant_env": "prod"}``."""
    action: ApprovalAction = "require_approval"
    """Decision the rule produces when it matches."""


class AgentApprovalSettings(BaseModel):
    """Human-in-the-loop policy of the agent."""

    default: ApprovalDefault = "deny"
    """Decision used when no rule matches a destructive tool."""
    rules: list[AgentApprovalRule] = Field(default_factory=list)
    """Rules evaluated in order; the first match wins."""


class AgentToolsSettings(BaseModel):
    """Tool exposure of the agent."""

    allowlist: list[str] | None = None
    """When set, only these tool names are exposed."""
    denylist: list[str] = Field(default_factory=list)
    """Tool names that are never exposed, applied after ``allowlist``."""
    redact_argument_keys: list[str] = Field(default_factory=lambda: list(DEFAULT_REDACT_KEYS))
    """Argument names masked in the preview that reaches the browser."""
    approval: AgentApprovalSettings = Field(default_factory=AgentApprovalSettings)


class MlflowSettings(BaseModel):
    """Optional MLflow tracing."""

    enabled: bool = False
    """Whether runs are recorded in MLflow; disabled adds no import and no cost."""
    tracking_uri: str = "http://localhost:5000"
    """MLflow tracking server URL."""
    experiment_name: str = "etlalchemy-agent"
    """Experiment the runs are logged to."""
    run_tags: dict[str, str] = Field(default_factory=dict)
    """Tags attached to every recorded run."""


class AgentObservabilitySettings(BaseModel):
    """Observability settings of the agent."""

    mlflow: MlflowSettings = Field(default_factory=MlflowSettings)


class AgentCheckpointSettings(BaseModel):
    """Settings of the LangGraph checkpointer.

    LangGraph creates its own ``checkpoints`` and ``checkpoint_writes`` tables.
    They are the one documented exception to the ``<context>_<plural>`` naming
    rule, because the library owns their shape.
    """

    enabled: bool = True
    """Whether runs are checkpointed so an approval can be resumed later."""
    sqlite_path: str | None = None
    """SQLite file of the checkpointer; defaults to ``database.sqlite_path``."""
    postgres_dsn: str | None = None
    """PostgreSQL DSN of the checkpointer; defaults to ``database.postgres_dsn``."""


class AgentSettings(BaseModel):
    """Settings of the agent runtime."""

    mcp_transport: Literal["in_process", "http"] = "in_process"
    """How the agent reaches the MCP server.

    ``in_process`` reuses the server object of this process, so no port, URL or
    bearer token is involved; ``http`` calls ``mcp_url`` like any other client
    and is the right choice when the agent runs in a separate process.
    """
    mcp_url: str = "http://127.0.0.1:8000/mcp"
    """Streamable HTTP endpoint of the MCP server; only used by ``http``."""
    auth: AgentAuthSettings = Field(default_factory=AgentAuthSettings)
    llm: LlmBootstrapSettings | None = None
    """Bootstrap provider; ``None`` skips the startup bootstrap entirely."""
    limits: AgentLimitsSettings = Field(default_factory=AgentLimitsSettings)
    tools: AgentToolsSettings = Field(default_factory=AgentToolsSettings)
    observability: AgentObservabilitySettings = Field(
        default_factory=AgentObservabilitySettings,
    )
    checkpoint: AgentCheckpointSettings = Field(default_factory=AgentCheckpointSettings)
    request_timeout_seconds: int = 30
    """Timeout of one MCP request that is not a tool call."""
    connect_retries: int = 3
    """Number of connection attempts before ``McpConnectionError`` is raised."""
    history_limit: int = 20
    """Number of previous messages replayed into a run."""


class McpSettings(BaseModel):
    """Settings of the MCP delivery layer."""

    require_auth: bool = True
    """Whether MCP clients must present a bearer token.

    Disable it only for local development or tests: without it every connected
    client can call every write tool.
    """


class ApiSettings(BaseModel):
    """Settings of the HTTP API."""

    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    cors_origins: list[str] = Field(default_factory=list)
    """Browser origins allowed to call the API; empty disables CORS entirely."""


class LoggingSettings(BaseModel):
    """Settings of the process-wide structured logger."""

    level: str = "INFO"
    """Minimum level, e.g. ``DEBUG`` / ``INFO`` / ``WARNING``."""

    mode: Literal["json", "stdout"] = "stdout"
    """Rendering mode: one JSON object per line, or human-readable stdout."""

    color: bool = True
    """ANSI colours for ``mode=stdout``; ignored when ``mode=json``."""

    quiet: list[str] = Field(
        default_factory=lambda: [
            "uvicorn.access",
            "httpx",
            "httpcore",
            "databricks.sdk",
            "psycopg",
            "sqlalchemy.engine",
        ],
    )
    """Loggers silenced completely, set above ``CRITICAL`` so nothing is emitted."""

    loggers: dict[str, str] = Field(default_factory=dict)
    """Per-logger level overrides, e.g. ``{"uvicorn": "WARNING"}``.

    Applied after ``quiet``, so an entry for the same logger wins over ``quiet``.
    """


class AppSettings(BaseSettings):
    """Top-level settings loaded from YAML files and environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="ETLALCHEMY_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    catalog: CatalogSettings = Field(default_factory=CatalogSettings)
    ingestion: IngestionSettings = Field(default_factory=IngestionSettings)
    vocabulary: VocabularySettings = Field(default_factory=VocabularySettings)
    semantic: SemanticSettings = Field(default_factory=SemanticSettings)
    comment: CommentSettings = Field(default_factory=CommentSettings)
    iam: IamSettings = Field(default_factory=IamSettings)
    llm_config: LlmConfigSettings = Field(default_factory=LlmConfigSettings)
    conversation: ConversationSettings = Field(default_factory=ConversationSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    mcp: McpSettings = Field(default_factory=McpSettings)
    cipher_key: str | None = None
    """Base64-encoded AES key (16/24/32 bytes); enables event encryption when set."""

    @model_validator(mode="after")
    def _validate_agent_llm_secret(self) -> AppSettings:
        """Rejects an inline bootstrap token when events are not encrypted.

        An inline token is stored inside the event state, so without a
        ``cipher_key`` it would sit in the event store in plaintext.

        Returns:
            The validated settings.

        Raises:
            ValueError: When ``agent.llm.token`` is set without ``cipher_key``.
        """
        llm = self.agent.llm
        if llm is not None and llm.token is not None and self.cipher_key is None:
            msg = "agent.llm.token requires cipher_key: set credential_ref instead"
            raise ValueError(msg)
        return self

    @field_validator("cipher_key")
    @classmethod
    def _validate_cipher_key(cls, value: str | None) -> str | None:
        """Rejects a key that is not base64 or does not decode to 16/24/32 bytes."""
        if value is None:
            return None
        try:
            raw = base64.b64decode(value, validate=True)
        except Exception as exc:  # binascii.Error, ValueError
            msg = "cipher_key must be valid base64"
            raise ValueError(msg) from exc
        if len(raw) not in (16, 24, 32):
            msg = "cipher_key must decode to 16, 24 or 32 bytes"
            raise ValueError(msg)
        return value

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Lets environment variables win over the values loaded from YAML."""
        return (env_settings, init_settings, dotenv_settings, file_secret_settings)

    def database_for(self, context: str) -> DatabaseSettings:
        """Returns the resolved database settings of a bounded context.

        A context without its own ``database`` block inherits the global settings
        (the same object, so the container can share one datastore). A context
        with overrides gets a merged and re-validated copy.
        """
        context_settings = getattr(self, context, None)
        override = getattr(context_settings, "database", None)
        if not isinstance(override, DatabaseOverride):
            return self.database
        return override.merge_onto(self.database)
