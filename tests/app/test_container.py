"""Tests for the dependency injection container."""

import base64
from collections.abc import Callable
from pathlib import Path

from dependency_injector import providers

from etlalchemy._vendor.eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore
from etlalchemy.app.bootstrap import Container
from etlalchemy.catalog.projection.sqlalchemy import SQLAlchemyCatalogView
from etlalchemy.comment.projection.sqlalchemy import SQLAlchemyCommentView
from etlalchemy.ingestion.projection.sqlalchemy import SQLAlchemyIngestionView
from etlalchemy.semantic.projection.sqlalchemy import SQLAlchemySemanticView
from etlalchemy.vocabulary.projection.sqlalchemy import SQLAlchemyVocabularyView


async def test_catalog_shares_the_global_datastore(
    config_dir: Path,
    write_config: Callable[[str], None],
    container: Container,
) -> None:
    """Without an override the catalog uses the same datastore instance."""
    write_config(f"database:\n  backend: sqlite\n  sqlite_path: {config_dir.parent / 'global.db'}\n")

    assert container.catalog_datastore() is container.global_datastore()


async def test_catalog_owns_its_datastore_when_overridden(
    config_dir: Path,
    write_config: Callable[[str], None],
    container: Container,
) -> None:
    """A context override gets its own datastore instance."""
    write_config(
        f"database:\n  backend: sqlite\n  sqlite_path: {config_dir.parent / 'global.db'}\n"
        f"catalog:\n  database:\n    sqlite_path: {config_dir.parent / 'catalog.db'}\n"
    )

    assert container.catalog_datastore() is not container.global_datastore()


async def test_catalog_view_is_the_async_view(
    config_dir: Path,
    write_config: Callable[[str], None],
    container: Container,
) -> None:
    """The catalog view is the async SQLAlchemy view."""
    write_config(f"database:\n  backend: sqlite\n  sqlite_path: {config_dir.parent / 'global.db'}\n")

    view = container.catalog_view()

    assert isinstance(view, SQLAlchemyCatalogView)
    assert view.tracking_table.name == "catalog_projection_tracking"


async def test_catalog_application_uses_the_resolved_environment(
    config_dir: Path,
    write_config: Callable[[str], None],
    container: Container,
) -> None:
    """The application receives the eventsourcing environment of its context."""
    write_config(f"database:\n  backend: sqlite\n  sqlite_path: {config_dir.parent / 'global.db'}\n")
    application = container.catalog_application()
    try:
        expected = container.settings().database_for("catalog").to_eventsourcing_env()
        for key, value in expected.items():
            assert application.env[key] == value
    finally:
        await application.aclose()


async def test_catalog_providers_agree_on_the_resolved_database(
    config_dir: Path,
    write_config: Callable[[str], None],
    container: Container,
) -> None:
    """The intermediate providers derive from the same resolved database."""
    write_config(f"database:\n  backend: sqlite\n  sqlite_path: {config_dir.parent / 'global.db'}\n")

    database = container.catalog_database()

    assert database.backend == "sqlite"
    assert container.catalog_env() == database.to_eventsourcing_env()


async def test_catalog_application_env_matches_catalog_env(
    config_dir: Path,
    write_config: Callable[[str], None],
    container: Container,
) -> None:
    """The application environment contains the catalog environment values."""
    write_config(f"database:\n  backend: sqlite\n  sqlite_path: {config_dir.parent / 'global.db'}\n")
    application = container.catalog_application()
    try:
        for key, value in container.catalog_env().items():
            assert application.env[key] == value
    finally:
        await application.aclose()


async def test_override_catalog_datastore(
    config_dir: Path,
    write_config: Callable[[str], None],
    container: Container,
) -> None:
    """Overriding the datastore provider feeds the view builder."""
    write_config(f"database:\n  backend: sqlite\n  sqlite_path: {config_dir.parent / 'global.db'}\n")
    fake = AsyncSQLAlchemyDatastore(f"sqlite+aiosqlite:///{config_dir.parent / 'fake.db'}")
    container.catalog_datastore.override(providers.Object(fake))
    try:
        view = container.catalog_view()
        assert isinstance(view, SQLAlchemyCatalogView)
        assert view.datastore is fake
    finally:
        container.catalog_datastore.reset_override()
        await fake.close()


async def test_ingestion_shares_the_global_datastore(
    config_dir: Path,
    write_config: Callable[[str], None],
    container: Container,
) -> None:
    """Without an override the ingestion context uses the global datastore."""
    write_config(f"database:\n  backend: sqlite\n  sqlite_path: {config_dir.parent / 'global.db'}\n")

    assert container.ingestion_datastore() is container.global_datastore()


async def test_ingestion_owns_its_datastore_when_overridden(
    config_dir: Path,
    write_config: Callable[[str], None],
    container: Container,
) -> None:
    """An ingestion override gets its own datastore instance."""
    write_config(
        f"database:\n  backend: sqlite\n  sqlite_path: {config_dir.parent / 'global.db'}\n"
        f"ingestion:\n  database:\n    sqlite_path: {config_dir.parent / 'ingestion.db'}\n"
    )

    assert container.ingestion_datastore() is not container.global_datastore()


async def test_ingestion_view_is_the_async_view(
    config_dir: Path,
    write_config: Callable[[str], None],
    container: Container,
) -> None:
    """The ingestion view is the async SQLAlchemy view."""
    write_config(f"database:\n  backend: sqlite\n  sqlite_path: {config_dir.parent / 'global.db'}\n")

    view = container.ingestion_view()

    assert isinstance(view, SQLAlchemyIngestionView)
    assert view.tracking_table.name == "ingestion_projection_tracking"


async def test_ingestion_application_uses_the_resolved_environment(
    config_dir: Path,
    write_config: Callable[[str], None],
    container: Container,
) -> None:
    """The ingestion application receives the environment of its context."""
    write_config(f"database:\n  backend: sqlite\n  sqlite_path: {config_dir.parent / 'global.db'}\n")
    application = container.ingestion_application()
    try:
        expected = container.settings().database_for("ingestion").to_eventsourcing_env()
        for key, value in expected.items():
            assert application.env[key] == value
        assert application.name == "ingestion_application"
    finally:
        await application.aclose()


CIPHER_KEY = base64.b64encode(b"0" * 32).decode()
"""Fixed 32-byte AES key used by the cipher wiring test."""


async def test_vocabulary_shares_the_global_datastore(
    config_dir: Path,
    write_config: Callable[[str], None],
    container: Container,
) -> None:
    """Without an override the vocabulary context uses the global datastore."""
    write_config(f"database:\n  backend: sqlite\n  sqlite_path: {config_dir.parent / 'global.db'}\n")

    assert container.vocabulary_datastore() is container.global_datastore()


async def test_vocabulary_view_is_the_async_view(
    config_dir: Path,
    write_config: Callable[[str], None],
    container: Container,
) -> None:
    """The vocabulary view is the async SQLAlchemy view."""
    write_config(f"database:\n  backend: sqlite\n  sqlite_path: {config_dir.parent / 'global.db'}\n")

    view = container.vocabulary_view()

    assert isinstance(view, SQLAlchemyVocabularyView)
    assert view.tracking_table.name == "vocabulary_projection_tracking"


async def test_vocabulary_application_uses_the_resolved_environment(
    config_dir: Path,
    write_config: Callable[[str], None],
    container: Container,
) -> None:
    """The vocabulary application receives the environment of its context."""
    write_config(f"database:\n  backend: sqlite\n  sqlite_path: {config_dir.parent / 'global.db'}\n")
    application = container.vocabulary_application()
    try:
        expected = container.settings().database_for("vocabulary").to_eventsourcing_env()
        for key, value in expected.items():
            assert application.env[key] == value
        assert application.name == "vocabulary_application"
    finally:
        await application.aclose()


async def test_semantic_shares_the_global_datastore(
    config_dir: Path,
    write_config: Callable[[str], None],
    container: Container,
) -> None:
    """Without an override the semantic context uses the global datastore."""
    write_config(f"database:\n  backend: sqlite\n  sqlite_path: {config_dir.parent / 'global.db'}\n")

    assert container.semantic_datastore() is container.global_datastore()


async def test_semantic_view_is_the_async_view(
    config_dir: Path,
    write_config: Callable[[str], None],
    container: Container,
) -> None:
    """The semantic view is the async SQLAlchemy view."""
    write_config(f"database:\n  backend: sqlite\n  sqlite_path: {config_dir.parent / 'global.db'}\n")

    view = container.semantic_view()

    assert isinstance(view, SQLAlchemySemanticView)
    assert view.tracking_table.name == "semantic_projection_tracking"


async def test_semantic_application_uses_the_resolved_environment(
    config_dir: Path,
    write_config: Callable[[str], None],
    container: Container,
) -> None:
    """The semantic application receives the environment of its context."""
    write_config(f"database:\n  backend: sqlite\n  sqlite_path: {config_dir.parent / 'global.db'}\n")
    application = container.semantic_application()
    try:
        expected = container.settings().database_for("semantic").to_eventsourcing_env()
        for key, value in expected.items():
            assert application.env[key] == value
        assert application.name == "semantic_application"
    finally:
        await application.aclose()


async def test_every_context_receives_the_cipher_key(
    config_dir: Path,
    write_config: Callable[[str], None],
    container: Container,
) -> None:
    """The catalog, ingestion and vocabulary applications all encrypt their events."""
    write_config(
        f"database:\n  backend: sqlite\n  sqlite_path: {config_dir.parent / 'shared.db'}\n"
        f"cipher_key: {CIPHER_KEY}\n"
    )

    assert container.catalog_env()["CIPHER_KEY"] == CIPHER_KEY
    assert container.ingestion_env()["CIPHER_KEY"] == CIPHER_KEY
    assert container.vocabulary_env()["CIPHER_KEY"] == CIPHER_KEY
    assert container.semantic_env()["CIPHER_KEY"] == CIPHER_KEY
    assert container.comment_env()["CIPHER_KEY"] == CIPHER_KEY
    assert container.catalog_application().env["CIPHER_KEY"] == CIPHER_KEY
    assert container.ingestion_application().env["CIPHER_KEY"] == CIPHER_KEY
    assert container.vocabulary_application().env["CIPHER_KEY"] == CIPHER_KEY
    assert container.semantic_application().env["CIPHER_KEY"] == CIPHER_KEY
    assert container.comment_application().env["CIPHER_KEY"] == CIPHER_KEY


async def test_comment_shares_the_global_datastore(
    config_dir: Path,
    write_config: Callable[[str], None],
    container: Container,
) -> None:
    """Without an override the comment context uses the global datastore."""
    write_config(f"database:\n  backend: sqlite\n  sqlite_path: {config_dir.parent / 'global.db'}\n")

    assert container.comment_datastore() is container.global_datastore()


async def test_comment_view_is_the_async_view(
    config_dir: Path,
    write_config: Callable[[str], None],
    container: Container,
) -> None:
    """The comment view is the async SQLAlchemy view."""
    write_config(f"database:\n  backend: sqlite\n  sqlite_path: {config_dir.parent / 'global.db'}\n")

    view = container.comment_view()

    assert isinstance(view, SQLAlchemyCommentView)
    assert view.tracking_table.name == "comment_projection_tracking"
