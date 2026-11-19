"""Tests for event encryption at rest through the AES cipher."""

from __future__ import annotations

import base64
import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest
from etlalchemy.app.bootstrap.factories import get_catalog_env, get_ingestion_env
from etlalchemy.app.config.settings import AppSettings, DatabaseSettings
from etlalchemy.catalog.application import CatalogApplication
from etlalchemy.ingestion.adapters.secrets_composite import CompositeSecretsResolver
from etlalchemy.ingestion.application import IngestionApplication

CIPHER_KEY = base64.b64encode(b"7" * 32).decode()
"""Fixed 32-byte AES key, so the tests do not depend on random material."""

TOKEN = "dbx-token-that-must-not-leak"
"""Inline credential written to the event store by the tests."""


class _NullConnectionsView:
    """Connections read model that knows no connection names."""

    async def find_connection_by_name(self, name: str) -> None:
        """Always reports an unknown name."""


def _database(path: Path) -> DatabaseSettings:
    """Returns SQLite database settings pointing at the given file."""
    return DatabaseSettings(backend="sqlite", sqlite_path=str(path))


def _ingestion_env(path: Path, cipher_key: str | None) -> dict[str, str]:
    """Returns the ingestion environment for the given store and key."""
    settings = AppSettings(database=_database(path), cipher_key=cipher_key)
    return get_ingestion_env(settings)


def _catalog_env(path: Path, cipher_key: str | None) -> dict[str, str]:
    """Returns the catalog environment for the given store and key."""
    settings = AppSettings(database=_database(path), cipher_key=cipher_key)
    return get_catalog_env(settings)


def _ingestion_application(env: dict[str, str]) -> IngestionApplication:
    """Builds an ingestion application over the given eventsourcing environment."""
    view = _NullConnectionsView()
    return IngestionApplication(
        catalog=CatalogApplication(env=env),
        catalog_view=cast(Any, view),
        connections_view=cast(Any, view),
        factories={"fake": cast(Any, object())},
        secrets=CompositeSecretsResolver({}),
        env=env,
    )


def _stored_states(path: Path, table: str) -> list[bytes]:
    """Returns the raw ``state`` column of every event stored in the SQLite file."""
    connection = sqlite3.connect(str(path))
    try:
        rows = connection.execute(f"SELECT state FROM {table}").fetchall()
    finally:
        connection.close()
    return [row[0] if isinstance(row[0], bytes) else str(row[0]).encode() for row in rows]


async def test_inline_token_encrypted_at_rest(tmp_path: Path) -> None:
    """An inline token is encrypted in the event store and decrypted on load."""
    path = tmp_path / "ingestion.db"
    async with _ingestion_application(_ingestion_env(path, CIPHER_KEY)) as application:
        connection_id = await application.create_connection(
            name="warehouse",
            kind="fake",
            endpoint="https://dbc.example.com",
            token=TOKEN,
        )
        connection = await application.get_connection(connection_id)
        assert connection.token == TOKEN

    states = _stored_states(path, "ingestion_application_events")

    assert states
    assert all(TOKEN.encode() not in state for state in states)


async def test_catalog_events_encrypted_at_rest(tmp_path: Path) -> None:
    """The catalog application receives the cipher as well."""
    path = tmp_path / "catalog.db"
    async with CatalogApplication(env=_catalog_env(path, CIPHER_KEY)) as application:
        catalog_id = await application.create_catalog("secret-catalog")
        catalog = await application.get_catalog(catalog_id)
        assert catalog.name == "secret-catalog"

    states = _stored_states(path, "catalog_application_events")

    assert states
    assert all(b"secret-catalog" not in state for state in states)


async def test_plaintext_events_stay_readable_without_a_key(tmp_path: Path) -> None:
    """Without a key the store keeps the plaintext behaviour of the old code."""
    path = tmp_path / "plain.db"
    async with _ingestion_application(_ingestion_env(path, None)) as application:
        connection_id = await application.create_connection(
            name="warehouse",
            kind="fake",
            endpoint="https://dbc.example.com",
            token=TOKEN,
        )
        connection = await application.get_connection(connection_id)
        assert connection.token == TOKEN

    states = _stored_states(path, "ingestion_application_events")

    assert states
    assert any(TOKEN.encode() in state for state in states)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "eventsourcing 9.5.6 decrypts every stored event as soon as a cipher is "
        "configured (Mapper.to_domain_event), so events written in plaintext "
        "before the key was enabled cannot be read afterwards"
    ),
)
async def test_legacy_plaintext_events_still_readable(tmp_path: Path) -> None:
    """Events written without a cipher cannot be read once encryption is enabled."""
    path = tmp_path / "legacy.db"
    async with _ingestion_application(_ingestion_env(path, None)) as plaintext:
        connection_id = await plaintext.create_connection(
            name="warehouse",
            kind="fake",
            endpoint="https://dbc.example.com",
            token=TOKEN,
        )

    async with _ingestion_application(_ingestion_env(path, CIPHER_KEY)) as encrypted:
        connection = await encrypted.get_connection(connection_id)
        assert connection.token == TOKEN
