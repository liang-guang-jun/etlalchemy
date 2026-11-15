"""Infrastructure factories for the assembly layer.

The factories build async datastores, materialised views and projection
resources. They do not depend on dependency-injector, so they can be tested
without a container.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

from eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore
from langchain_core.language_models import BaseChatModel

from etlalchemy.agent.checkpoint import CheckpointSettings
from etlalchemy.agent.errors import LlmProviderError
from etlalchemy.agent.factory import AgentFactory, ConnectorFactory
from etlalchemy.agent.runtime import ChatModelFactory
from etlalchemy.agent.settings import AgentLimits, AgentRuntimeSettings, ApprovalRule
from etlalchemy.app.config.settings import AppSettings, DatabaseSettings
from etlalchemy.catalog.projection.projection import run_catalog_projection
from etlalchemy.catalog.projection.sqlalchemy import SQLAlchemyCatalogView
from etlalchemy.comment.adapters.iam import IamCommentAuthorizationAdapter
from etlalchemy.comment.adapters.target_lookup import CompositeTargetLookup
from etlalchemy.comment.application import CommentOptions
from etlalchemy.comment.projection.projection import run_comment_projection
from etlalchemy.comment.projection.sqlalchemy import SQLAlchemyCommentView
from etlalchemy.conversation.adapters.iam import IamConversationAuthorizationAdapter
from etlalchemy.conversation.application import ConversationApplication, ConversationOptions
from etlalchemy.conversation.projection.projection import run_conversation_projection
from etlalchemy.conversation.projection.sqlalchemy import SQLAlchemyConversationView
from etlalchemy.iam.adapters.passwords import PasswordHasher
from etlalchemy.iam.adapters.secrets import EnvSecretsResolver
from etlalchemy.iam.application import IamApplication, IamOptions
from etlalchemy.iam.authorization import CasbinAuthorizer
from etlalchemy.iam.projection.projection import run_iam_projection
from etlalchemy.iam.projection.sqlalchemy import SQLAlchemyIamView
from etlalchemy.ingestion.adapters.databricks import DatabricksSourceFactory
from etlalchemy.ingestion.adapters.postgres import PostgresSourceFactory
from etlalchemy.ingestion.adapters.secrets_composite import CompositeSecretsResolver
from etlalchemy.ingestion.adapters.secrets_env import EnvSecretsProvider
from etlalchemy.ingestion.adapters.secrets_file import FileSecretsProvider
from etlalchemy.ingestion.ports.data_source import DataSourceFactory
from etlalchemy.ingestion.ports.secrets import SecretsProvider
from etlalchemy.ingestion.projection.projection import run_ingestion_projection
from etlalchemy.ingestion.projection.sqlalchemy import SQLAlchemyIngestionView
from etlalchemy.llm_config.adapters.chat_models import build_chat_model
from etlalchemy.llm_config.adapters.iam import IamLlmConfigAuthorizationAdapter
from etlalchemy.llm_config.application import LlmConfigApplication, LlmConfigOptions
from etlalchemy.llm_config.projection.projection import run_llm_config_projection
from etlalchemy.llm_config.projection.sqlalchemy import SQLAlchemyLlmProviderView
from etlalchemy.semantic.projection.projection import run_semantic_projection
from etlalchemy.semantic.projection.sqlalchemy import SQLAlchemySemanticView
from etlalchemy.shared.credentials import profile_reference
from etlalchemy.vocabulary.projection.projection import run_vocabulary_projection
from etlalchemy.vocabulary.projection.sqlalchemy import SQLAlchemyVocabularyView

Datastore = AsyncSQLAlchemyDatastore
"""Asynchronous datastore shared by the event stores and the read models."""

CIPHER_TOPIC = "eventsourcing.cipher:AESCipher"
"""Topic of the AES cipher that eventsourcing instantiates from CIPHER_KEY."""


def with_cipher(env: dict[str, str], cipher_key: str | None) -> dict[str, str]:
    """Returns a copy of ``env`` with CIPHER_TOPIC/CIPHER_KEY added when a key is set.

    Args:
        env: The eventsourcing environment of one bounded context.
        cipher_key: The validated base64 AES key, or ``None`` for plaintext.

    Returns:
        The unchanged ``env`` when no key is configured, otherwise a copy that
        enables :class:`eventsourcing.cipher.AESCipher`.
    """
    if not cipher_key:
        return env
    encrypted = dict(env)
    encrypted["CIPHER_TOPIC"] = CIPHER_TOPIC
    encrypted["CIPHER_KEY"] = cipher_key
    return encrypted


def build_datastore(database: DatabaseSettings) -> AsyncSQLAlchemyDatastore:
    """Builds the async datastore described by the given settings."""
    url = database.to_eventsourcing_env()["SQLALCHEMY_URL"]
    return AsyncSQLAlchemyDatastore(url)


async def datastore_lifecycle(datastore: Datastore) -> AsyncIterator[None]:
    """Disposes the datastore engine when the container shuts down.

    The datastore itself is a synchronous singleton so it can be injected into
    synchronous providers; this resource only owns its shutdown.
    """
    try:
        yield None
    finally:
        await datastore.close()


class CatalogViewFactory:
    """Builds the catalog read model and its projection resource."""

    @staticmethod
    def build(
        datastore: Datastore,
        tracking_table_name: str,
    ) -> SQLAlchemyCatalogView:
        """Builds the catalog view on the given datastore."""
        return SQLAlchemyCatalogView(
            datastore=datastore,
            tracking_table=datastore.create_tracking_table(tracking_table_name),
        )

    @staticmethod
    async def projection_resource(
        env: dict[str, str],
        enabled: bool,
    ) -> AsyncIterator[Any]:
        """Runs the catalog projection for the lifetime of the resource."""
        if not enabled:
            yield None
            return
        runner = run_catalog_projection(env)
        await runner.start()
        try:
            yield runner
        finally:
            # The runner owns its application, view and datastore.
            await runner.stop()


class IngestionViewFactory:
    """Builds the ingestion read model and its projection resource."""

    @staticmethod
    def build(
        datastore: Datastore,
        tracking_table_name: str,
    ) -> SQLAlchemyIngestionView:
        """Builds the ingestion view on the given datastore."""
        return SQLAlchemyIngestionView(
            datastore=datastore,
            tracking_table=datastore.create_tracking_table(tracking_table_name),
        )

    @staticmethod
    async def projection_resource(
        env: dict[str, str],
        enabled: bool,
    ) -> AsyncIterator[Any]:
        """Runs the ingestion projection for the lifetime of the resource."""
        if not enabled:
            yield None
            return
        runner = run_ingestion_projection(env)
        await runner.start()
        try:
            yield runner
        finally:
            # The runner owns its application, view and datastore.
            await runner.stop()


class VocabularyViewFactory:
    """Builds the vocabulary read model and its projection resource."""

    @staticmethod
    def build(
        datastore: Datastore,
        tracking_table_name: str,
    ) -> SQLAlchemyVocabularyView:
        """Builds the vocabulary view on the given datastore."""
        return SQLAlchemyVocabularyView(
            datastore=datastore,
            tracking_table=datastore.create_tracking_table(tracking_table_name),
        )

    @staticmethod
    async def projection_resource(
        env: dict[str, str],
        enabled: bool,
    ) -> AsyncIterator[Any]:
        """Runs the vocabulary projection for the lifetime of the resource."""
        if not enabled:
            yield None
            return
        runner = run_vocabulary_projection(env)
        await runner.start()
        try:
            yield runner
        finally:
            # The runner owns its application, view and datastore.
            await runner.stop()


class SemanticViewFactory:
    """Builds the semantic read model and its projection resource."""

    @staticmethod
    def build(
        datastore: Datastore,
        tracking_table_name: str,
    ) -> SQLAlchemySemanticView:
        """Builds the semantic view on the given datastore."""
        return SQLAlchemySemanticView(
            datastore=datastore,
            tracking_table=datastore.create_tracking_table(tracking_table_name),
        )

    @staticmethod
    async def projection_resource(
        env: dict[str, str],
        enabled: bool,
    ) -> AsyncIterator[Any]:
        """Runs the semantic projection for the lifetime of the resource."""
        if not enabled:
            yield None
            return
        runner = run_semantic_projection(env)
        await runner.start()
        try:
            yield runner
        finally:
            # The runner owns its application, view and datastore.
            await runner.stop()


class CommentViewFactory:
    """Builds the comment read model and its projection resource."""

    @staticmethod
    def build(
        datastore: Datastore,
        tracking_table_name: str,
    ) -> SQLAlchemyCommentView:
        """Builds the comment view on the given datastore."""
        return SQLAlchemyCommentView(
            datastore=datastore,
            tracking_table=datastore.create_tracking_table(tracking_table_name),
        )

    @staticmethod
    async def projection_resource(
        env: dict[str, str],
        enabled: bool,
    ) -> AsyncIterator[Any]:
        """Runs the comment projection for the lifetime of the resource."""
        if not enabled:
            yield None
            return
        runner = run_comment_projection(env)
        await runner.start()
        try:
            yield runner
        finally:
            # The runner owns its application, view and datastore.
            await runner.stop()


def get_database_for(settings: AppSettings, context: str) -> DatabaseSettings:
    """Returns the resolved database settings of the given context."""
    return settings.database_for(context)


def get_catalog_env(settings: AppSettings) -> dict[str, str]:
    """Returns the eventsourcing environment of the catalog context, with cipher.

    Args:
        settings: The resolved application settings.

    Returns:
        The catalog datastore environment, plus the AES cipher keys when
        ``cipher_key`` is configured.
    """
    return with_cipher(
        get_eventsourcing_env(settings.database_for("catalog")),
        settings.cipher_key,
    )


def get_ingestion_env(settings: AppSettings) -> dict[str, str]:
    """Returns the eventsourcing environment of the ingestion context, with cipher.

    Args:
        settings: The resolved application settings.

    Returns:
        The ingestion datastore environment, plus the AES cipher keys when
        ``cipher_key`` is configured.
    """
    return with_cipher(
        get_eventsourcing_env(settings.database_for("ingestion")),
        settings.cipher_key,
    )


def get_vocabulary_env(settings: AppSettings) -> dict[str, str]:
    """Returns the eventsourcing environment of the vocabulary context, with cipher.

    Args:
        settings: The resolved application settings.

    Returns:
        The vocabulary datastore environment, plus the AES cipher keys when
        ``cipher_key`` is configured.
    """
    return with_cipher(
        get_eventsourcing_env(settings.database_for("vocabulary")),
        settings.cipher_key,
    )


def get_semantic_env(settings: AppSettings) -> dict[str, str]:
    """Returns the eventsourcing environment of the semantic context, with cipher.

    Args:
        settings: The resolved application settings.

    Returns:
        The semantic datastore environment, plus the AES cipher keys when
        ``cipher_key`` is configured.
    """
    return with_cipher(
        get_eventsourcing_env(settings.database_for("semantic")),
        settings.cipher_key,
    )


def get_comment_env(settings: AppSettings) -> dict[str, str]:
    """Returns the eventsourcing environment of the comment context, with cipher.

    Args:
        settings: The resolved application settings.

    Returns:
        The comment datastore environment, plus the AES cipher keys when
        ``cipher_key`` is configured.
    """
    return with_cipher(
        get_eventsourcing_env(settings.database_for("comment")),
        settings.cipher_key,
    )


def get_comment_options(settings: AppSettings) -> CommentOptions:
    """Returns the runtime knobs of the comment application service."""
    return CommentOptions(
        max_body_length=settings.comment.max_body_length,
        max_title_length=settings.comment.max_title_length,
        max_mentions_per_comment=settings.comment.max_mentions_per_comment,
        max_comments_per_thread=settings.comment.max_comments_per_thread,
        soft_max_reply_depth=settings.comment.soft_max_reply_depth,
        depth_warning_message=settings.comment.depth_warning_message,
        default_page_size=settings.comment.default_page_size,
        max_page_size=settings.comment.max_page_size,
        validate_target_exists=settings.comment.validate_target_exists,
        enforce_target_tenant=settings.comment.enforce_target_tenant,
        read_requires_session=settings.comment.read_requires_session,
        allow_multiple_threads=settings.comment.allow_multiple_threads,
        target_types=frozenset(settings.comment.target_types),
    )


def get_comment_target_lookup(
    catalog_view: SQLAlchemyCatalogView,
    semantic_view: SQLAlchemySemanticView,
    vocabulary_view: SQLAlchemyVocabularyView,
    ingestion_view: SQLAlchemyIngestionView,
    iam_view: SQLAlchemyIamView,
) -> CompositeTargetLookup:
    """Builds the composite lookup that resolves comment targets."""
    return CompositeTargetLookup(
        catalog_view=catalog_view,
        semantic_view=semantic_view,
        vocabulary_view=vocabulary_view,
        ingestion_view=ingestion_view,
        iam_view=iam_view,
    )


def get_comment_authorization(
    iam_application: IamApplication,
    iam_view: SQLAlchemyIamView,
    target_lookup: CompositeTargetLookup,
    options: CommentOptions,
) -> IamCommentAuthorizationAdapter:
    """Builds the IAM adapter behind the comment authorization port."""
    return IamCommentAuthorizationAdapter(
        iam=iam_application,
        iam_view=iam_view,
        target_lookup=target_lookup,
        options=options,
    )


def get_iam_env(settings: AppSettings) -> dict[str, str]:
    """Returns the eventsourcing environment of the IAM context, with cipher.

    Args:
        settings: The resolved application settings.

    Returns:
        The IAM datastore environment, plus the AES cipher keys when
        ``cipher_key`` is configured.
    """
    return with_cipher(
        get_eventsourcing_env(settings.database_for("iam")),
        settings.cipher_key,
    )


def get_iam_hasher() -> PasswordHasher:
    """Returns the Argon2id password hasher of the IAM context."""
    return PasswordHasher()


def get_iam_secrets_resolver(settings: AppSettings) -> EnvSecretsResolver:
    """Returns the ``env:``/``file:`` resolver used for provider credentials."""
    root = (
        Path(settings.iam.secrets_file_root).expanduser()
        if settings.iam.secrets_file_root
        else None
    )
    return EnvSecretsResolver(root)


def get_iam_authorizer(settings: AppSettings) -> CasbinAuthorizer:
    """Returns the Casbin authorizer with its configured cache lifetime."""
    return CasbinAuthorizer(settings.iam.policy.reload_interval_seconds)


def get_iam_options(settings: AppSettings) -> IamOptions:
    """Returns the runtime knobs of the IAM application service."""
    return IamOptions(
        password_min_length=settings.iam.password_min_length,
        max_api_keys=settings.iam.max_api_keys,
        api_key_grace_max_days=settings.iam.api_key_grace_max_days,
        max_group_depth=settings.iam.max_group_depth,
        password_session_minutes=settings.iam.password_session_minutes,
        oidc_session_minutes=settings.iam.oidc_session_minutes,
        api_key_session_minutes=settings.iam.api_key_session_minutes,
        api_key_pepper=settings.iam.api_key_pepper,
        record_denied_authorizations=settings.iam.record_denied_authorizations,
    )


def get_mcp_session_id() -> UUID:
    """Returns the session id of the authenticated MCP caller.

    The import is deferred so the assembly layer never imports FastMCP while the
    container class is being defined.
    """
    from etlalchemy.app.mcp.auth import current_session_id

    return current_session_id()


class IamViewFactory:
    """Builds the IAM read model and its projection resource."""

    @staticmethod
    def build(
        datastore: Datastore,
        tracking_table_name: str,
    ) -> SQLAlchemyIamView:
        """Builds the IAM view on the given datastore."""
        return SQLAlchemyIamView(
            datastore=datastore,
            tracking_table=datastore.create_tracking_table(tracking_table_name),
        )

    @staticmethod
    async def projection_resource(
        env: dict[str, str],
        enabled: bool,
    ) -> AsyncIterator[Any]:
        """Runs the IAM projection for the lifetime of the resource."""
        if not enabled:
            yield None
            return
        runner = run_iam_projection(env)
        await runner.start()
        try:
            yield runner
        finally:
            # The runner owns its application, view and datastore.
            await runner.stop()


def get_secrets_resolver(settings: AppSettings) -> CompositeSecretsResolver:
    """Builds the composite credential resolver from the configured providers."""
    providers: dict[str, SecretsProvider] = {"env": EnvSecretsProvider()}
    root = (
        Path(settings.ingestion.secrets.file_root).expanduser()
        if settings.ingestion.secrets.file_root
        else None
    )
    providers["file"] = FileSecretsProvider(root)
    return CompositeSecretsResolver(providers)


def get_source_factories(settings: AppSettings) -> dict[str, DataSourceFactory]:
    """Returns the enabled source factories keyed by source kind."""
    known: dict[str, DataSourceFactory] = {
        "databricks": DatabricksSourceFactory(),
        "postgres": PostgresSourceFactory(),
    }
    return {kind: known[kind] for kind in settings.ingestion.source_kinds if kind in known}


def get_eventsourcing_env(database: DatabaseSettings) -> dict[str, str]:
    """Returns the eventsourcing environment for the given database."""
    return database.to_eventsourcing_env()


def get_datastore_scope(settings: AppSettings, database: DatabaseSettings) -> str:
    """Returns ``shared`` when the context database is the global one."""
    return "shared" if database is settings.database else "dedicated"


class LlmConfigViewFactory:
    """Builds the LLM provider read model and its projection resource."""

    @staticmethod
    def build(
        datastore: Datastore,
        tracking_table_name: str,
    ) -> SQLAlchemyLlmProviderView:
        """Builds the LLM provider view on the given datastore."""
        return SQLAlchemyLlmProviderView(
            datastore=datastore,
            tracking_table=datastore.create_tracking_table(tracking_table_name),
        )

    @staticmethod
    async def projection_resource(
        env: dict[str, str],
        enabled: bool,
    ) -> AsyncIterator[Any]:
        """Runs the LLM provider projection for the lifetime of the resource."""
        if not enabled:
            yield None
            return
        runner = run_llm_config_projection(env)
        await runner.start()
        try:
            yield runner
        finally:
            # The runner owns its application, view and datastore.
            await runner.stop()


class ConversationViewFactory:
    """Builds the conversation read model and its projection resource."""

    @staticmethod
    def build(
        datastore: Datastore,
        tracking_table_name: str,
    ) -> SQLAlchemyConversationView:
        """Builds the conversation view on the given datastore."""
        return SQLAlchemyConversationView(
            datastore=datastore,
            tracking_table=datastore.create_tracking_table(tracking_table_name),
        )

    @staticmethod
    async def projection_resource(
        env: dict[str, str],
        enabled: bool,
    ) -> AsyncIterator[Any]:
        """Runs the conversation projection for the lifetime of the resource."""
        if not enabled:
            yield None
            return
        runner = run_conversation_projection(env)
        await runner.start()
        try:
            yield runner
        finally:
            # The runner owns its application, view and datastore.
            await runner.stop()


def get_llm_config_env(settings: AppSettings) -> dict[str, str]:
    """Returns the eventsourcing environment of the LLM provider context."""
    return with_cipher(
        get_eventsourcing_env(settings.database_for("llm_config")),
        settings.cipher_key,
    )


def get_conversation_env(settings: AppSettings) -> dict[str, str]:
    """Returns the eventsourcing environment of the conversation context."""
    return with_cipher(
        get_eventsourcing_env(settings.database_for("conversation")),
        settings.cipher_key,
    )


def get_llm_config_authorization(
    iam_application: IamApplication,
    iam_view: SQLAlchemyIamView,
) -> IamLlmConfigAuthorizationAdapter:
    """Builds the IAM adapter of the LLM provider authorization port."""
    return IamLlmConfigAuthorizationAdapter(iam_application, iam_view)


def get_conversation_authorization(
    iam_application: IamApplication,
) -> IamConversationAuthorizationAdapter:
    """Builds the IAM adapter of the conversation authorization port."""
    return IamConversationAuthorizationAdapter(iam_application)


def get_llm_config_options(settings: AppSettings) -> LlmConfigOptions:
    """Builds the LLM provider options from the application settings."""
    return LlmConfigOptions(
        default_page_size=settings.conversation.default_page_size,
        max_page_size=settings.conversation.max_page_size,
    )


def get_conversation_options(settings: AppSettings) -> ConversationOptions:
    """Builds the conversation options from the application settings."""
    return ConversationOptions(
        max_message_chars=settings.conversation.max_message_chars,
        max_assistant_chars=settings.conversation.max_message_chars,
        default_page_size=settings.conversation.default_page_size,
        max_page_size=settings.conversation.max_page_size,
    )


def get_agent_runtime_settings(settings: AppSettings) -> AgentRuntimeSettings:
    """Builds the runtime settings from the application settings.

    Args:
        settings: The resolved application settings.

    Returns:
        The plain value object the agent package consumes.
    """
    agent = settings.agent
    allowlist = frozenset(agent.tools.allowlist) if agent.tools.allowlist else None
    return AgentRuntimeSettings(
        mcp_url=agent.mcp_url,
        transport=agent.mcp_transport,
        request_timeout_seconds=float(agent.request_timeout_seconds),
        connect_retries=agent.connect_retries,
        history_limit=agent.history_limit,
        limits=AgentLimits(
            max_tool_calls=agent.limits.max_tool_calls,
            max_wall_clock_seconds=agent.limits.max_wall_clock_seconds,
            tool_timeout_seconds=agent.limits.tool_timeout_seconds,
            max_tool_output_chars=agent.limits.max_tool_output_chars,
            max_tool_args_chars=agent.limits.max_tool_args_chars,
            max_tool_result_preview_chars=agent.limits.max_tool_result_preview_chars,
            max_reasoning_chars=agent.limits.max_reasoning_chars,
            token_budget=agent.limits.token_budget,
        ),
        allowlist=allowlist,
        denylist=frozenset(agent.tools.denylist),
        redact_argument_keys=frozenset(agent.tools.redact_argument_keys),
        approval_default=agent.tools.approval.default,
        approval_rules=tuple(
            ApprovalRule(match=rule.match, when=dict(rule.when), action=rule.action)
            for rule in agent.tools.approval.rules
        ),
    )


def get_checkpoint_settings(settings: AppSettings) -> CheckpointSettings:
    """Builds the checkpointer settings from the database backend.

    Args:
        settings: The resolved application settings.

    Returns:
        The backend, and the connection details it needs.
    """
    checkpoint = settings.agent.checkpoint
    if not checkpoint.enabled:
        return CheckpointSettings(backend="none")
    database = settings.database
    if database.backend == "postgres":
        return CheckpointSettings(
            backend="postgres",
            postgres_dsn=checkpoint.postgres_dsn or database.postgres_dsn,
        )
    return CheckpointSettings(
        backend="sqlite",
        sqlite_path=checkpoint.sqlite_path or database.sqlite_path,
    )


def get_chat_model_factory(llm: LlmConfigApplication) -> ChatModelFactory:
    """Builds the factory that resolves the chat model of one run.

    Args:
        llm: The LLM provider application.

    Returns:
        A coroutine that resolves a provider and builds its chat model.
    """

    async def factory(
        provider_id: UUID | None,
        user_id: UUID,
        tenant_id: UUID | None,
    ) -> BaseChatModel:
        row = await llm.runtime_provider(provider_id, user_id, tenant_id)
        if row is None:
            msg = "no LLM provider is configured; create one or set agent.llm"
            raise LlmProviderError(msg)
        profile = profile_reference(row.credential_ref)
        credential = None if profile is not None else await llm.credential_for(row.provider_id)
        return await asyncio.to_thread(
            build_chat_model,
            kind=row.kind,
            credential=credential,
            default_model=row.default_model,
            endpoint=row.endpoint,
            options=row.options,
            profile=profile,
        )

    return factory


def build_agent_factory(
    settings: AgentRuntimeSettings,
    conversation: ConversationApplication,
    llm: LlmConfigApplication,
    checkpointer: Any | None,
    server: Any | None,
) -> AgentFactory:
    """Builds the agent factory the routes drive.

    Args:
        settings: Runtime limits and policy.
        conversation: Conversation store the runs write to.
        llm: LLM configuration used to resolve one provider per run.
        checkpointer: Durable saver, or ``None`` when disabled.
        server: ``MCPServer`` of this process, used by the in-process transport.

    Returns:
        The factory the streaming and non-streaming routes build runners from.
    """
    return AgentFactory(
        settings=settings,
        conversation=conversation,
        chat_model_factory=get_chat_model_factory(llm),
        checkpointer=checkpointer,
        connector_factory=(
            get_in_process_connector_factory(server) if settings.transport == "in_process" else None
        ),
    )


def build_mcp_server(container: Any) -> Any:
    """Builds the MCP server of this process.

    The import is deferred so the assembly layer never imports FastMCP while the
    container class is being defined; the same instance serves the ``/mcp`` route
    and the in-process agent transport.

    Args:
        container: The DI container the contexts and applications live on.

    Returns:
        The mounted ``MCPServer``.
    """
    from etlalchemy.app.mcp.server import MCPServer

    return MCPServer(container)


def get_in_process_connector_factory(server: Any | None) -> ConnectorFactory:
    """Builds the connector factory that keeps MCP calls inside the process.

    The import is deferred so the assembly layer never imports FastMCP while the
    container class is being defined.

    Args:
        server: ``MCPServer`` of this process, or ``None`` when none was built.

    Returns:
        A callable that binds a connector to one caller.
    """
    from etlalchemy.app.mcp.inprocess import InProcessConnector
    from etlalchemy.app.mcp.server import MCPServer

    if not isinstance(server, MCPServer):
        msg = "agent.mcp_transport 'in_process' needs the MCP server of this process"
        raise ValueError(msg)
    mcp = server.mcp

    def factory(headers: Mapping[str, str], session_id: UUID | None) -> InProcessConnector:
        """Binds one connector to the caller behind the request."""
        del headers  # An in-process call carries no bearer token.
        return InProcessConnector(mcp, session_id=session_id)

    return factory
