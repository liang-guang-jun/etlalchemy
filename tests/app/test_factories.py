"""Tests for the infrastructure factories."""

import base64
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from etlalchemy.app.bootstrap.factories import (
    CatalogViewFactory,
    CommentViewFactory,
    IngestionViewFactory,
    SemanticViewFactory,
    VocabularyViewFactory,
    build_datastore,
    datastore_lifecycle,
    get_catalog_env,
    get_chat_model_factory,
    get_comment_env,
    get_ingestion_env,
    get_secrets_resolver,
    get_semantic_env,
    get_source_factories,
    get_vocabulary_env,
    with_cipher,
)
from etlalchemy.app.config.settings import AppSettings, DatabaseSettings
from etlalchemy.catalog.projection.sqlalchemy import SQLAlchemyCatalogView
from etlalchemy.comment.projection.sqlalchemy import SQLAlchemyCommentView
from etlalchemy.ingestion.adapters.databricks import DatabricksSourceFactory
from etlalchemy.ingestion.adapters.postgres import PostgresSourceFactory
from etlalchemy.ingestion.adapters.secrets_composite import CompositeSecretsResolver
from etlalchemy.ingestion.projection.sqlalchemy import SQLAlchemyIngestionView
from etlalchemy.semantic.projection.sqlalchemy import SQLAlchemySemanticView
from etlalchemy.vocabulary.projection.sqlalchemy import SQLAlchemyVocabularyView
from eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore


async def test_datastore_factory_builds_sqlite(tmp_path: Path) -> None:
    """The SQLite backend produces an aiosqlite engine."""
    settings = DatabaseSettings(backend="sqlite", sqlite_path=str(tmp_path / "view.db"))

    datastore = build_datastore(settings)
    try:
        assert isinstance(datastore, AsyncSQLAlchemyDatastore)
        assert datastore.url.startswith("sqlite+aiosqlite")
    finally:
        await datastore.close()


async def test_datastore_factory_builds_postgres() -> None:
    """The Postgres backend produces a psycopg async engine without connecting."""
    settings = DatabaseSettings(
        backend="postgres",
        postgres_dsn="postgresql://user:pass@localhost:5432/dbname",
    )

    datastore = build_datastore(settings)
    try:
        assert datastore.url.startswith("postgresql+psycopg")
        assert datastore.url.endswith("/dbname")
    finally:
        await datastore.close()


async def test_datastore_resource_closes_the_datastore() -> None:
    """The lifecycle resource closes the datastore when the generator is closed."""
    closed: list[bool] = []

    class _FakeDatastore:
        async def close(self) -> None:
            closed.append(True)

    fake = _FakeDatastore()

    resource = datastore_lifecycle(fake)  # type: ignore[arg-type]
    try:
        assert await anext(resource) is None
    finally:
        await resource.aclose()

    assert closed == [True]


async def test_view_factories_build_the_async_views(tmp_path: Path) -> None:
    """Each view factory wires the view to the datastore's tracking table."""
    datastore = build_datastore(DatabaseSettings(sqlite_path=str(tmp_path / "view.db")))
    try:
        catalog_view = CatalogViewFactory.build(datastore, "catalog_projection_tracking")
        ingestion_view = IngestionViewFactory.build(datastore, "ingestion_projection_tracking")
        vocabulary_view = VocabularyViewFactory.build(
            datastore,
            "vocabulary_projection_tracking",
        )
        semantic_view = SemanticViewFactory.build(datastore, "semantic_projection_tracking")
        comment_view = CommentViewFactory.build(datastore, "comment_projection_tracking")

        assert isinstance(catalog_view, SQLAlchemyCatalogView)
        assert isinstance(ingestion_view, SQLAlchemyIngestionView)
        assert isinstance(vocabulary_view, SQLAlchemyVocabularyView)
        assert isinstance(semantic_view, SQLAlchemySemanticView)
        assert isinstance(comment_view, SQLAlchemyCommentView)
        assert catalog_view.datastore is datastore
        assert catalog_view.tracking_table.name == "catalog_projection_tracking"
        assert ingestion_view.tracking_table.name == "ingestion_projection_tracking"
        assert vocabulary_view.tracking_table.name == "vocabulary_projection_tracking"
        assert semantic_view.tracking_table.name == "semantic_projection_tracking"
        assert comment_view.tracking_table.name == "comment_projection_tracking"
    finally:
        await datastore.close()


async def test_projection_resource_is_disabled_without_running_the_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disabled projection yields None and never starts a runner."""

    def fail(env: object) -> None:
        raise AssertionError("run_catalog_projection must not be called")

    monkeypatch.setattr("etlalchemy.app.bootstrap.factories.run_catalog_projection", fail)

    resource: AsyncIterator[object] = CatalogViewFactory.projection_resource(
        env={},
        enabled=False,
    )
    try:
        assert await anext(resource) is None
    finally:
        await resource.aclose()


async def test_ingestion_projection_resource_is_disabled_without_running_the_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disabled ingestion projection yields None and never starts a runner."""

    def fail(env: object) -> None:
        raise AssertionError("run_ingestion_projection must not be called")

    monkeypatch.setattr("etlalchemy.app.bootstrap.factories.run_ingestion_projection", fail)

    resource: AsyncIterator[object] = IngestionViewFactory.projection_resource(
        env={},
        enabled=False,
    )
    try:
        assert await anext(resource) is None
    finally:
        await resource.aclose()


async def test_vocabulary_projection_resource_is_disabled_without_running_the_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disabled vocabulary projection yields None and never starts a runner."""

    def fail(env: object) -> None:
        raise AssertionError("run_vocabulary_projection must not be called")

    monkeypatch.setattr("etlalchemy.app.bootstrap.factories.run_vocabulary_projection", fail)

    resource: AsyncIterator[object] = VocabularyViewFactory.projection_resource(
        env={},
        enabled=False,
    )
    try:
        assert await anext(resource) is None
    finally:
        await resource.aclose()


async def test_semantic_projection_resource_is_disabled_without_running_the_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disabled semantic projection yields None and never starts a runner."""

    def fail(env: object) -> None:
        raise AssertionError("run_semantic_projection must not be called")

    monkeypatch.setattr("etlalchemy.app.bootstrap.factories.run_semantic_projection", fail)

    resource: AsyncIterator[object] = SemanticViewFactory.projection_resource(
        env={},
        enabled=False,
    )
    try:
        assert await anext(resource) is None
    finally:
        await resource.aclose()


async def test_comment_projection_resource_is_disabled_without_running_the_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disabled comment projection yields None and never starts a runner."""

    def fail(env: object) -> None:
        raise AssertionError("run_comment_projection must not be called")

    monkeypatch.setattr("etlalchemy.app.bootstrap.factories.run_comment_projection", fail)

    resource: AsyncIterator[object] = CommentViewFactory.projection_resource(
        env={},
        enabled=False,
    )
    try:
        assert await anext(resource) is None
    finally:
        await resource.aclose()


def test_source_factories_follow_the_settings() -> None:
    """The configured source kinds become factories keyed by kind."""
    factories = get_source_factories(AppSettings())

    assert isinstance(factories["databricks"], DatabricksSourceFactory)
    assert isinstance(factories["postgres"], PostgresSourceFactory)
    assert get_source_factories(AppSettings(ingestion={"source_kinds": ["unknown"]})) == {}


class _FakeLlmConfig:
    """Minimal LLM configuration the chat model factory resolves against."""

    def __init__(self, row: Any, credentials: dict[UUID, str]) -> None:
        self.row = row
        self.credentials = credentials
        self.resolved: list[UUID] = []

    async def runtime_provider(
        self,
        provider_id: UUID | None,
        user_id: UUID,
        tenant_id: UUID | None,
    ) -> Any:
        return self.row

    async def credential_for(self, provider_id: UUID) -> str:
        self.resolved.append(provider_id)
        return self.credentials[provider_id]


async def test_chat_model_factory_skips_the_key_for_a_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A profile provider is built without resolving an API key."""
    provider_id = uuid4()
    row = SimpleNamespace(
        provider_id=provider_id,
        kind="databricks_ai_gateway",
        credential_ref="profile:team",
        default_model="databricks-claude-sonnet-4-5",
        endpoint=None,
        options={},
    )
    llm = _FakeLlmConfig(row, {})
    captured: dict[str, Any] = {}

    def fake_build(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr("etlalchemy.app.bootstrap.factories.build_chat_model", fake_build)

    await get_chat_model_factory(llm)(None, uuid4(), None)  # type: ignore[arg-type]

    assert captured["profile"] == "team"
    assert captured["credential"] is None
    assert llm.resolved == []


async def test_chat_model_factory_resolves_the_key_without_a_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A regular provider still resolves its credential reference."""
    provider_id = uuid4()
    row = SimpleNamespace(
        provider_id=provider_id,
        kind="openai",
        credential_ref="env:OPENAI_API_KEY",
        default_model="gpt-4o-mini",
        endpoint=None,
        options={},
    )
    llm = _FakeLlmConfig(row, {provider_id: "sk-test"})
    captured: dict[str, Any] = {}

    def fake_build(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr("etlalchemy.app.bootstrap.factories.build_chat_model", fake_build)

    await get_chat_model_factory(llm)(None, uuid4(), None)  # type: ignore[arg-type]

    assert captured["profile"] is None
    assert captured["credential"] == "sk-test"
    assert llm.resolved == [provider_id]


async def test_secrets_resolver_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default resolver handles ``env:`` references."""
    monkeypatch.setenv("DBX_TOKEN", "from-env")

    resolver = get_secrets_resolver(AppSettings())

    assert isinstance(resolver, CompositeSecretsResolver)
    assert (await resolver.resolve("env:DBX_TOKEN")).value == "from-env"


async def test_secrets_resolver_uses_the_file_root(tmp_path: Path) -> None:
    """``file:`` references resolve relative to the configured root."""
    (tmp_path / "token").write_text("from-file", encoding="utf-8")
    settings = AppSettings(ingestion={"secrets": {"file_root": str(tmp_path)}})

    resolver = get_secrets_resolver(settings)

    assert (await resolver.resolve("file:token")).value == "from-file"


CIPHER_KEY = base64.b64encode(b"0" * 32).decode()
"""Fixed 32-byte AES key used by the cipher tests."""


def _context_envs(settings: AppSettings) -> list[dict[str, str]]:
    """Returns the eventsourcing environment of every bounded context."""
    return [
        get_catalog_env(settings),
        get_ingestion_env(settings),
        get_semantic_env(settings),
        get_vocabulary_env(settings),
        get_comment_env(settings),
    ]


def test_cipher_key_none_keeps_plaintext_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a cipher key the environments stay identical to the database env."""
    monkeypatch.delenv("ETLALCHEMY_CIPHER_KEY", raising=False)
    settings = AppSettings()

    for env, context in zip(
        _context_envs(settings),
        ["catalog", "ingestion", "semantic", "vocabulary", "comment"],
        strict=True,
    ):
        assert env == settings.database_for(context).to_eventsourcing_env()
        assert "CIPHER_TOPIC" not in env
        assert "CIPHER_KEY" not in env


def test_cipher_key_adds_cipher_topic() -> None:
    """A configured key adds the AES cipher topic and the raw key to both contexts."""
    settings = AppSettings(cipher_key=CIPHER_KEY)

    for env in _context_envs(settings):
        assert env["CIPHER_TOPIC"] == "eventsourcing.cipher:AESCipher"
        assert env["CIPHER_KEY"] == CIPHER_KEY


def test_catalog_env_carries_cipher_for_a_shared_datastore(tmp_path: Path) -> None:
    """With no per-context override both environments share the store and the cipher."""
    settings = AppSettings(
        database={"backend": "sqlite", "sqlite_path": str(tmp_path / "shared.db")},
        cipher_key=CIPHER_KEY,
    )
    assert settings.database_for("catalog") is settings.database_for("ingestion")

    catalog_env = get_catalog_env(settings)
    ingestion_env = get_ingestion_env(settings)
    vocabulary_env = get_vocabulary_env(settings)
    semantic_env = get_semantic_env(settings)
    comment_env = get_comment_env(settings)

    assert catalog_env["SQLALCHEMY_URL"] == ingestion_env["SQLALCHEMY_URL"]
    assert catalog_env["SQLALCHEMY_URL"] == vocabulary_env["SQLALCHEMY_URL"]
    assert catalog_env["SQLALCHEMY_URL"] == semantic_env["SQLALCHEMY_URL"]
    assert catalog_env["SQLALCHEMY_URL"] == comment_env["SQLALCHEMY_URL"]
    assert catalog_env["CIPHER_KEY"] == ingestion_env["CIPHER_KEY"] == CIPHER_KEY
    assert vocabulary_env["CIPHER_KEY"] == CIPHER_KEY
    assert semantic_env["CIPHER_KEY"] == CIPHER_KEY
    assert comment_env["CIPHER_KEY"] == CIPHER_KEY


def test_with_cipher_returns_the_same_mapping_without_a_key() -> None:
    """``with_cipher`` never copies or mutates the environment without a key."""
    env = {"PERSISTENCE_MODULE": "eventsourcing.asyncio.sqlalchemy"}

    assert with_cipher(env, None) is env
    assert with_cipher(env, "") is env
    assert with_cipher(env, CIPHER_KEY) == {
        "PERSISTENCE_MODULE": "eventsourcing.asyncio.sqlalchemy",
        "CIPHER_TOPIC": "eventsourcing.cipher:AESCipher",
        "CIPHER_KEY": CIPHER_KEY,
    }
    assert "CIPHER_KEY" not in env
