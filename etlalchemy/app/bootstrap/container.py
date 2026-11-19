"""Dependency injection container for the assembly layer."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from dependency_injector import containers, providers

from etlalchemy.agent.checkpoint import open_checkpointer
from etlalchemy.app.auth import SessionAuthenticator
from etlalchemy.app.bootstrap.factories import (
    CatalogViewFactory,
    CommentViewFactory,
    ConversationViewFactory,
    Datastore,
    IamViewFactory,
    IngestionViewFactory,
    LlmConfigViewFactory,
    SemanticViewFactory,
    VocabularyViewFactory,
    build_agent_factory,
    build_datastore,
    context_datastore_lifecycle,
    datastore_lifecycle,
    get_agent_runtime_settings,
    get_catalog_env,
    get_checkpoint_settings,
    get_comment_authorization,
    get_comment_env,
    get_comment_options,
    get_comment_target_lookup,
    get_conversation_authorization,
    get_conversation_env,
    get_conversation_options,
    get_database_for,
    get_datastore_scope,
    get_iam_authorizer,
    get_iam_env,
    get_iam_hasher,
    get_iam_options,
    get_iam_secrets_resolver,
    get_ingestion_env,
    get_llm_config_authorization,
    get_llm_config_env,
    get_llm_config_options,
    get_mcp_session_id,
    get_secrets_resolver,
    get_semantic_env,
    get_source_factories,
    get_vocabulary_env,
)
from etlalchemy.app.config.loader import load_settings
from etlalchemy.app.config.settings import AppSettings, DatabaseSettings
from etlalchemy.catalog.application import CatalogApplication
from etlalchemy.catalog.projection.sqlalchemy import SQLAlchemyCatalogView
from etlalchemy.comment.application import CommentApplication
from etlalchemy.comment.projection.sqlalchemy import SQLAlchemyCommentView
from etlalchemy.conversation.application import ConversationApplication
from etlalchemy.conversation.projection.sqlalchemy import SQLAlchemyConversationView
from etlalchemy.iam.application import IamApplication
from etlalchemy.iam.projection.sqlalchemy import SQLAlchemyIamView
from etlalchemy.ingestion.application import IngestionApplication
from etlalchemy.ingestion.projection.sqlalchemy import SQLAlchemyIngestionView
from etlalchemy.llm_config.application import LlmConfigApplication
from etlalchemy.llm_config.projection.sqlalchemy import SQLAlchemyLlmProviderView
from etlalchemy.semantic.application import ModelApplication
from etlalchemy.semantic.projection.sqlalchemy import SQLAlchemySemanticView
from etlalchemy.vocabulary.application import VocabularyApplication
from etlalchemy.vocabulary.projection.sqlalchemy import SQLAlchemyVocabularyView

CATALOG_CONTEXT = "catalog"
IAM_CONTEXT = "iam"
INGESTION_CONTEXT = "ingestion"
VOCABULARY_CONTEXT = "vocabulary"
SEMANTIC_CONTEXT = "semantic"
COMMENT_CONTEXT = "comment"
LLM_CONFIG_CONTEXT = "llm_config"
CONVERSATION_CONTEXT = "conversation"


class Container(containers.DeclarativeContainer):
    """Wires settings, datastores, applications and projections."""

    wiring_config = containers.WiringConfiguration(
        modules=[
            "etlalchemy.app.api.dependencies.auth",
            "etlalchemy.app.api.routes.agent",
            "etlalchemy.app.api.routes.catalog",
            "etlalchemy.app.api.routes.iam",
            "etlalchemy.app.api.routes.comment",
            "etlalchemy.app.api.routes.ingestion",
            "etlalchemy.app.api.routes.semantic",
            "etlalchemy.app.api.routes.vocabulary",
        ],
    )

    # -- configuration -----------------------------------------------------
    settings: providers.Singleton[AppSettings] = providers.Singleton(load_settings)

    # -- resolved context configuration ------------------------------------
    catalog_database: providers.Callable[DatabaseSettings] = providers.Callable(
        get_database_for,
        settings=settings,
        context=CATALOG_CONTEXT,
    )
    catalog_env: providers.Callable[dict[str, str]] = providers.Callable(
        get_catalog_env,
        settings=settings,
    )
    catalog_is_shared: providers.Callable[str] = providers.Callable(
        get_datastore_scope,
        settings=settings,
        database=catalog_database,
    )

    # -- datastores --------------------------------------------------------
    global_datastore: providers.Singleton[Datastore] = providers.Singleton(
        build_datastore,
        database=settings.provided.database,
    )
    global_datastore_lifecycle: providers.Resource[None] = providers.Resource(
        datastore_lifecycle,
        datastore=global_datastore,
    )
    catalog_datastore: providers.Selector = providers.Selector(
        catalog_is_shared,
        shared=global_datastore,
        dedicated=providers.Singleton(
            build_datastore,
            database=catalog_database,
        ),
    )
    catalog_datastore_lifecycle: providers.Resource[None] = providers.Resource(
        context_datastore_lifecycle,
        datastore=catalog_datastore,
        scope=catalog_is_shared,
    )

    # -- application -------------------------------------------------------
    catalog_application: providers.Singleton[CatalogApplication] = providers.Singleton(
        CatalogApplication,
        env=catalog_env,
    )

    # -- read model --------------------------------------------------------
    catalog_view: providers.Singleton[SQLAlchemyCatalogView] = providers.Singleton(
        CatalogViewFactory.build,
        datastore=catalog_datastore,
        tracking_table_name=settings.provided.catalog.projection.tracking_table_name,
    )

    # -- projection --------------------------------------------------------
    catalog_projection_runner: providers.Resource[Any] = providers.Resource(
        CatalogViewFactory.projection_resource,
        env=catalog_env,
        enabled=settings.provided.catalog.projection.enabled,
    )

    # -- iam configuration -------------------------------------------------
    iam_database: providers.Callable[DatabaseSettings] = providers.Callable(
        get_database_for,
        settings=settings,
        context=IAM_CONTEXT,
    )
    iam_env: providers.Callable[dict[str, str]] = providers.Callable(
        get_iam_env,
        settings=settings,
    )
    iam_is_shared: providers.Callable[str] = providers.Callable(
        get_datastore_scope,
        settings=settings,
        database=iam_database,
    )

    # -- iam datastore -----------------------------------------------------
    iam_datastore: providers.Selector = providers.Selector(
        iam_is_shared,
        shared=global_datastore,
        dedicated=providers.Singleton(
            build_datastore,
            database=iam_database,
        ),
    )
    iam_datastore_lifecycle: providers.Resource[None] = providers.Resource(
        context_datastore_lifecycle,
        datastore=iam_datastore,
        scope=iam_is_shared,
    )

    # -- iam application and read model ------------------------------------
    iam_view: providers.Singleton[SQLAlchemyIamView] = providers.Singleton(
        IamViewFactory.build,
        datastore=iam_datastore,
        tracking_table_name=settings.provided.iam.projection.tracking_table_name,
    )
    iam_hasher: providers.Singleton[Any] = providers.Singleton(get_iam_hasher)
    iam_secrets_resolver: providers.Singleton[Any] = providers.Singleton(
        get_iam_secrets_resolver,
        settings=settings,
    )
    iam_authorizer: providers.Singleton[Any] = providers.Singleton(
        get_iam_authorizer,
        settings=settings,
    )
    iam_options: providers.Callable[Any] = providers.Callable(
        get_iam_options,
        settings=settings,
    )
    iam_application: providers.Singleton[IamApplication] = providers.Singleton(
        IamApplication,
        view=iam_view,
        hasher=iam_hasher,
        secrets_resolver=iam_secrets_resolver,
        authorizer=iam_authorizer,
        options=iam_options,
        env=iam_env,
    )

    # -- iam projection ----------------------------------------------------
    iam_projection_runner: providers.Resource[Any] = providers.Resource(
        IamViewFactory.projection_resource,
        env=iam_env,
        enabled=settings.provided.iam.projection.enabled,
    )

    # -- shared authentication ---------------------------------------------
    session_authenticator: providers.Singleton[SessionAuthenticator] = providers.Singleton(
        SessionAuthenticator,
        iam=iam_application,
        token_prefix=settings.provided.iam.bearer_token_prefix,
    )
    mcp_session_resolver: providers.Callable[UUID] = providers.Callable(
        # Tests override this provider to supply a session to the in-memory client.
        get_mcp_session_id,
    )

    # -- mcp server --------------------------------------------------------
    # The mounted ``MCPServer`` of this process. ``create_app`` registers it so
    # the ``/mcp`` route and the in-process agent transport share one instance;
    # it stays ``None`` in a container that never builds an HTTP application.
    mcp_server: providers.Object[Any] = providers.Object(None)

    # -- ingestion configuration ------------------------------------------
    ingestion_database: providers.Callable[DatabaseSettings] = providers.Callable(
        get_database_for,
        settings=settings,
        context=INGESTION_CONTEXT,
    )
    ingestion_env: providers.Callable[dict[str, str]] = providers.Callable(
        get_ingestion_env,
        settings=settings,
    )
    ingestion_is_shared: providers.Callable[str] = providers.Callable(
        get_datastore_scope,
        settings=settings,
        database=ingestion_database,
    )

    # -- ingestion datastore ----------------------------------------------
    ingestion_datastore: providers.Selector = providers.Selector(
        ingestion_is_shared,
        shared=global_datastore,
        dedicated=providers.Singleton(
            build_datastore,
            database=ingestion_database,
        ),
    )
    ingestion_datastore_lifecycle: providers.Resource[None] = providers.Resource(
        context_datastore_lifecycle,
        datastore=ingestion_datastore,
        scope=ingestion_is_shared,
    )

    # -- ingestion wiring --------------------------------------------------
    secrets_resolver: providers.Singleton[Any] = providers.Singleton(
        get_secrets_resolver,
        settings=settings,
    )
    source_factories: providers.Callable[dict[str, Any]] = providers.Callable(
        get_source_factories,
        settings=settings,
    )
    ingestion_view: providers.Singleton[SQLAlchemyIngestionView] = providers.Singleton(
        IngestionViewFactory.build,
        datastore=ingestion_datastore,
        tracking_table_name=settings.provided.ingestion.projection.tracking_table_name,
    )
    ingestion_application: providers.Singleton[IngestionApplication] = providers.Singleton(
        IngestionApplication,
        catalog=catalog_application,
        catalog_view=catalog_view,
        connections_view=ingestion_view,
        factories=source_factories,
        secrets=secrets_resolver,
        env=ingestion_env,
    )

    # -- ingestion projection ----------------------------------------------
    ingestion_projection_runner: providers.Resource[Any] = providers.Resource(
        IngestionViewFactory.projection_resource,
        env=ingestion_env,
        enabled=settings.provided.ingestion.projection.enabled,
    )

    # -- vocabulary configuration ------------------------------------------
    vocabulary_database: providers.Callable[DatabaseSettings] = providers.Callable(
        get_database_for,
        settings=settings,
        context=VOCABULARY_CONTEXT,
    )
    vocabulary_env: providers.Callable[dict[str, str]] = providers.Callable(
        get_vocabulary_env,
        settings=settings,
    )
    vocabulary_is_shared: providers.Callable[str] = providers.Callable(
        get_datastore_scope,
        settings=settings,
        database=vocabulary_database,
    )

    # -- vocabulary datastore ----------------------------------------------
    vocabulary_datastore: providers.Selector = providers.Selector(
        vocabulary_is_shared,
        shared=global_datastore,
        dedicated=providers.Singleton(
            build_datastore,
            database=vocabulary_database,
        ),
    )
    vocabulary_datastore_lifecycle: providers.Resource[None] = providers.Resource(
        context_datastore_lifecycle,
        datastore=vocabulary_datastore,
        scope=vocabulary_is_shared,
    )

    # -- vocabulary application and read model -----------------------------
    vocabulary_view: providers.Singleton[SQLAlchemyVocabularyView] = providers.Singleton(
        VocabularyViewFactory.build,
        datastore=vocabulary_datastore,
        tracking_table_name=settings.provided.vocabulary.projection.tracking_table_name,
    )
    vocabulary_application: providers.Singleton[VocabularyApplication] = providers.Singleton(
        VocabularyApplication,
        catalog_view=catalog_view,
        env=vocabulary_env,
    )

    # -- vocabulary projection ---------------------------------------------
    vocabulary_projection_runner: providers.Resource[Any] = providers.Resource(
        VocabularyViewFactory.projection_resource,
        env=vocabulary_env,
        enabled=settings.provided.vocabulary.projection.enabled,
    )

    # -- semantic configuration --------------------------------------------
    semantic_database: providers.Callable[DatabaseSettings] = providers.Callable(
        get_database_for,
        settings=settings,
        context=SEMANTIC_CONTEXT,
    )
    semantic_env: providers.Callable[dict[str, str]] = providers.Callable(
        get_semantic_env,
        settings=settings,
    )
    semantic_is_shared: providers.Callable[str] = providers.Callable(
        get_datastore_scope,
        settings=settings,
        database=semantic_database,
    )

    # -- semantic datastore -------------------------------------------------
    semantic_datastore: providers.Selector = providers.Selector(
        semantic_is_shared,
        shared=global_datastore,
        dedicated=providers.Singleton(
            build_datastore,
            database=semantic_database,
        ),
    )
    semantic_datastore_lifecycle: providers.Resource[None] = providers.Resource(
        context_datastore_lifecycle,
        datastore=semantic_datastore,
        scope=semantic_is_shared,
    )

    # -- semantic application and read model -------------------------------
    semantic_view: providers.Singleton[SQLAlchemySemanticView] = providers.Singleton(
        SemanticViewFactory.build,
        datastore=semantic_datastore,
        tracking_table_name=settings.provided.semantic.projection.tracking_table_name,
    )
    semantic_application: providers.Singleton[ModelApplication] = providers.Singleton(
        ModelApplication,
        catalog_view=catalog_view,
        env=semantic_env,
    )

    # -- semantic projection ------------------------------------------------
    semantic_projection_runner: providers.Resource[Any] = providers.Resource(
        SemanticViewFactory.projection_resource,
        env=semantic_env,
        enabled=settings.provided.semantic.projection.enabled,
    )

    # -- comment configuration ----------------------------------------------
    comment_database: providers.Callable[DatabaseSettings] = providers.Callable(
        get_database_for,
        settings=settings,
        context=COMMENT_CONTEXT,
    )
    comment_env: providers.Callable[dict[str, str]] = providers.Callable(
        get_comment_env,
        settings=settings,
    )
    comment_is_shared: providers.Callable[str] = providers.Callable(
        get_datastore_scope,
        settings=settings,
        database=comment_database,
    )

    # -- comment datastore ---------------------------------------------------
    comment_datastore: providers.Selector = providers.Selector(
        comment_is_shared,
        shared=global_datastore,
        dedicated=providers.Singleton(
            build_datastore,
            database=comment_database,
        ),
    )
    comment_datastore_lifecycle: providers.Resource[None] = providers.Resource(
        context_datastore_lifecycle,
        datastore=comment_datastore,
        scope=comment_is_shared,
    )

    # -- comment application and read model ----------------------------------
    comment_view: providers.Singleton[SQLAlchemyCommentView] = providers.Singleton(
        CommentViewFactory.build,
        datastore=comment_datastore,
        tracking_table_name=settings.provided.comment.projection.tracking_table_name,
    )
    comment_options: providers.Callable[Any] = providers.Callable(
        get_comment_options,
        settings=settings,
    )
    comment_target_lookup: providers.Singleton[Any] = providers.Singleton(
        get_comment_target_lookup,
        catalog_view=catalog_view,
        semantic_view=semantic_view,
        vocabulary_view=vocabulary_view,
        ingestion_view=ingestion_view,
        iam_view=iam_view,
    )
    comment_authorization: providers.Singleton[Any] = providers.Singleton(
        get_comment_authorization,
        iam_application=iam_application,
        iam_view=iam_view,
        target_lookup=comment_target_lookup,
        options=comment_options,
    )
    comment_application: providers.Singleton[CommentApplication] = providers.Singleton(
        CommentApplication,
        view=comment_view,
        iam=comment_authorization,
        target_lookup=comment_target_lookup,
        options=comment_options,
        env=comment_env,
    )

    # -- comment projection --------------------------------------------------
    comment_projection_runner: providers.Resource[Any] = providers.Resource(
        CommentViewFactory.projection_resource,
        env=comment_env,
        enabled=settings.provided.comment.projection.enabled,
    )

    # -- llm config configuration -------------------------------------------
    llm_config_database: providers.Callable[DatabaseSettings] = providers.Callable(
        get_database_for,
        settings=settings,
        context=LLM_CONFIG_CONTEXT,
    )
    llm_config_env: providers.Callable[dict[str, str]] = providers.Callable(
        get_llm_config_env,
        settings=settings,
    )
    llm_config_is_shared: providers.Callable[str] = providers.Callable(
        get_datastore_scope,
        settings=settings,
        database=llm_config_database,
    )

    # -- llm config datastore ------------------------------------------------
    llm_config_datastore: providers.Selector = providers.Selector(
        llm_config_is_shared,
        shared=global_datastore,
        dedicated=providers.Singleton(
            build_datastore,
            database=llm_config_database,
        ),
    )
    llm_config_datastore_lifecycle: providers.Resource[None] = providers.Resource(
        context_datastore_lifecycle,
        datastore=llm_config_datastore,
        scope=llm_config_is_shared,
    )

    # -- llm config application and read model --------------------------------
    llm_config_view: providers.Singleton[SQLAlchemyLlmProviderView] = providers.Singleton(
        LlmConfigViewFactory.build,
        datastore=llm_config_datastore,
        tracking_table_name=settings.provided.llm_config.projection.tracking_table_name,
    )
    llm_config_options: providers.Callable[Any] = providers.Callable(
        get_llm_config_options,
        settings=settings,
    )
    llm_config_authorization: providers.Singleton[Any] = providers.Singleton(
        get_llm_config_authorization,
        iam_application=iam_application,
        iam_view=iam_view,
    )
    llm_config_application: providers.Singleton[LlmConfigApplication] = providers.Singleton(
        LlmConfigApplication,
        view=llm_config_view,
        iam=llm_config_authorization,
        secrets=secrets_resolver,
        options=llm_config_options,
        env=llm_config_env,
    )

    # -- llm config projection ------------------------------------------------
    llm_config_projection_runner: providers.Resource[Any] = providers.Resource(
        LlmConfigViewFactory.projection_resource,
        env=llm_config_env,
        enabled=settings.provided.llm_config.projection.enabled,
    )

    # -- conversation configuration -------------------------------------------
    conversation_database: providers.Callable[DatabaseSettings] = providers.Callable(
        get_database_for,
        settings=settings,
        context=CONVERSATION_CONTEXT,
    )
    conversation_env: providers.Callable[dict[str, str]] = providers.Callable(
        get_conversation_env,
        settings=settings,
    )
    conversation_is_shared: providers.Callable[str] = providers.Callable(
        get_datastore_scope,
        settings=settings,
        database=conversation_database,
    )

    # -- conversation datastore ------------------------------------------------
    conversation_datastore: providers.Selector = providers.Selector(
        conversation_is_shared,
        shared=global_datastore,
        dedicated=providers.Singleton(
            build_datastore,
            database=conversation_database,
        ),
    )
    conversation_datastore_lifecycle: providers.Resource[None] = providers.Resource(
        context_datastore_lifecycle,
        datastore=conversation_datastore,
        scope=conversation_is_shared,
    )

    # -- conversation application and read model -------------------------------
    conversation_view: providers.Singleton[SQLAlchemyConversationView] = providers.Singleton(
        ConversationViewFactory.build,
        datastore=conversation_datastore,
        tracking_table_name=settings.provided.conversation.projection.tracking_table_name,
    )
    conversation_options: providers.Callable[Any] = providers.Callable(
        get_conversation_options,
        settings=settings,
    )
    conversation_authorization: providers.Singleton[Any] = providers.Singleton(
        get_conversation_authorization,
        iam_application=iam_application,
    )
    conversation_application: providers.Singleton[ConversationApplication] = providers.Singleton(
        ConversationApplication,
        view=conversation_view,
        iam=conversation_authorization,
        options=conversation_options,
        env=conversation_env,
    )

    # -- conversation projection ------------------------------------------------
    conversation_projection_runner: providers.Resource[Any] = providers.Resource(
        ConversationViewFactory.projection_resource,
        env=conversation_env,
        enabled=settings.provided.conversation.projection.enabled,
    )

    # -- agent --------------------------------------------------------------
    agent_settings: providers.Callable[Any] = providers.Callable(
        get_agent_runtime_settings,
        settings=settings,
    )
    agent_checkpoint_settings: providers.Callable[Any] = providers.Callable(
        get_checkpoint_settings,
        settings=settings,
    )
    agent_checkpointer: providers.Resource[Any] = providers.Resource(
        open_checkpointer,
        settings=agent_checkpoint_settings,
    )
    agent_factory: providers.Singleton[Any] = providers.Singleton(
        build_agent_factory,
        settings=agent_settings,
        conversation=conversation_application,
        llm=llm_config_application,
        checkpointer=agent_checkpointer,
        server=mcp_server,
    )
