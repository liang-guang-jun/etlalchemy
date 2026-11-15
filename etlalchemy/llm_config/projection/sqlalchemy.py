"""Asynchronous SQLAlchemy implementation of the LLM provider read model.

SQLAlchemy Core builds the table definitions and the DML statements; they are
executed on the async engine of
:class:`~eventsourcing.asyncio.sqlalchemy.AsyncSQLAlchemyDatastore`, so the view
change and its tracking record still share one transaction. The same class serves
SQLite (``aiosqlite``) and PostgreSQL (``psycopg``); only the upsert dialect
differs.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from eventsourcing.asyncio.sqlalchemy import (
    AsyncSQLAlchemyDatastore,
    AsyncSQLAlchemyTrackingRecorder,
)
from sqlalchemy import Select, and_, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from etlalchemy.llm_config.projection.tables import (
    llm_config_provider_defaults,
    llm_config_provider_shares,
    llm_config_providers,
    metadata,
)
from etlalchemy.llm_config.projection.view import (
    LlmProviderView,
    ProviderDefaultRow,
    ProviderRow,
    ProviderShareRow,
    as_uuid,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from eventsourcing.persistence import Tracking
    from sqlalchemy import Table
    from sqlalchemy.sql import ColumnElement


def _now() -> datetime:
    """Returns the current UTC timestamp written by the read model."""
    return datetime.now(UTC)


class SQLAlchemyLlmProviderView(AsyncSQLAlchemyTrackingRecorder, LlmProviderView):
    """Asynchronous materialised view of the LLM provider aggregate."""

    async def create_table(self) -> None:
        """Creates the tracking table and the view tables if they do not exist."""
        async with self.datastore.transaction() as conn:
            await conn.run_sync(metadata.create_all)
            await conn.run_sync(self.datastore.metadata.create_all)

    def _insert(self, table: Table) -> Any:
        """Returns the upsert construct of the configured dialect."""
        if self.datastore.dialect_name == AsyncSQLAlchemyDatastore.SQLITE:
            return sqlite_insert(table)
        return pg_insert(table)

    async def _write(self, statements: Sequence[Any], tracking: Tracking) -> None:
        """Applies the statements and records the tracking row atomically."""
        async with self.transaction() as conn:
            for statement in statements:
                await conn.execute(statement)
            await self.insert_tracking_in_transaction(conn, tracking)

    async def _fetch_all(self, statement: Select[Any]) -> Sequence[Any]:
        """Executes a read statement and returns all rows."""
        async with self.datastore.connection() as conn:
            rows: Sequence[Any] = (await conn.execute(statement)).all()
            return rows

    async def _fetch_one(self, statement: Select[Any]) -> Any:
        """Executes a read statement and returns the first row, or ``None``."""
        async with self.datastore.connection() as conn:
            return (await conn.execute(statement)).first()

    # -- writes -------------------------------------------------------------

    async def register_provider(
        self,
        provider_id: UUID,
        name: str,
        kind: str,
        endpoint: str | None,
        credential_ref: str | None,
        has_inline_credential: bool,
        default_model: str,
        options: dict[str, str],
        owner_user_id: UUID,
        tenant_id: UUID | None,
        is_public: bool,
        created_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Registers a provider, clearing a previous discarded marker."""
        statement = self._insert(llm_config_providers).values(
            provider_id=provider_id,
            name=name,
            kind=kind,
            endpoint=endpoint,
            credential_ref=credential_ref,
            has_inline_credential=has_inline_credential,
            default_model=default_model,
            options=json.dumps(options),
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            is_public=is_public,
            is_system_default=False,
            created_at=created_at,
            discarded_at=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[llm_config_providers.c.provider_id],
            set_={
                "name": statement.excluded.name,
                "kind": statement.excluded.kind,
                "endpoint": statement.excluded.endpoint,
                "credential_ref": statement.excluded.credential_ref,
                "has_inline_credential": statement.excluded.has_inline_credential,
                "default_model": statement.excluded.default_model,
                "options": statement.excluded.options,
                "owner_user_id": statement.excluded.owner_user_id,
                "tenant_id": statement.excluded.tenant_id,
                "is_public": statement.excluded.is_public,
                "discarded_at": statement.excluded.discarded_at,
            },
        )
        await self._write([statement], tracking)

    async def rename_provider(self, provider_id: UUID, name: str, tracking: Tracking) -> None:
        """Changes the name of a provider."""
        await self._write([self._update(provider_id, name=name)], tracking)

    async def change_endpoint(
        self,
        provider_id: UUID,
        endpoint: str | None,
        tracking: Tracking,
    ) -> None:
        """Changes the endpoint of a provider."""
        await self._write([self._update(provider_id, endpoint=endpoint)], tracking)

    async def change_default_model(
        self,
        provider_id: UUID,
        default_model: str,
        tracking: Tracking,
    ) -> None:
        """Changes the default model of a provider."""
        await self._write(
            [self._update(provider_id, default_model=default_model)],
            tracking,
        )

    async def change_options(
        self,
        provider_id: UUID,
        options: dict[str, str],
        tracking: Tracking,
    ) -> None:
        """Replaces the model options of a provider."""
        await self._write(
            [self._update(provider_id, options=json.dumps(options))],
            tracking,
        )

    async def rotate_credential(
        self,
        provider_id: UUID,
        credential_ref: str | None,
        has_inline_credential: bool,
        tracking: Tracking,
    ) -> None:
        """Updates the credential pointer of a provider."""
        statement = self._update(
            provider_id,
            credential_ref=credential_ref,
            has_inline_credential=has_inline_credential,
        )
        await self._write([statement], tracking)

    async def set_sharing(
        self,
        provider_id: UUID,
        user_ids: list[UUID],
        group_ids: list[UUID],
        tracking: Tracking,
    ) -> None:
        """Replaces every share of a provider."""
        statements: list[Any] = [
            delete(llm_config_provider_shares).where(
                llm_config_provider_shares.c.provider_id == provider_id
            )
        ]
        for scope, target_ids in (("user", user_ids), ("group", group_ids)):
            for target_id in dict.fromkeys(target_ids):
                insert = self._insert(llm_config_provider_shares).values(
                    provider_id=provider_id,
                    scope=scope,
                    target_id=target_id,
                )
                statements.append(
                    insert.on_conflict_do_nothing(
                        index_elements=[
                            llm_config_provider_shares.c.provider_id,
                            llm_config_provider_shares.c.scope,
                            llm_config_provider_shares.c.target_id,
                        ]
                    )
                )
        await self._write(statements, tracking)

    async def set_default(
        self,
        provider_id: UUID,
        scope: str,
        target_id: UUID | None,
        enabled: bool,
        tracking: Tracking,
    ) -> None:
        """Marks or unmarks a provider as the default of the given scope."""
        if scope == "system":
            await self._write(
                [self._update(provider_id, is_system_default=enabled)],
                tracking,
            )
            return
        pointer = and_(
            llm_config_provider_defaults.c.provider_id == provider_id,
            llm_config_provider_defaults.c.scope == scope,
            llm_config_provider_defaults.c.target_id == target_id,
        )
        if not enabled:
            await self._write(
                [delete(llm_config_provider_defaults).where(pointer)],
                tracking,
            )
            return
        insert = self._insert(llm_config_provider_defaults).values(
            provider_id=provider_id,
            scope=scope,
            target_id=target_id,
        )
        await self._write(
            [
                insert.on_conflict_do_nothing(
                    index_elements=[
                        llm_config_provider_defaults.c.provider_id,
                        llm_config_provider_defaults.c.scope,
                        llm_config_provider_defaults.c.target_id,
                    ]
                )
            ],
            tracking,
        )

    async def discard_provider(self, provider_id: UUID, tracking: Tracking) -> None:
        """Soft-deletes a provider and drops its shares and default pointers."""
        statements: list[Any] = [
            self._update(provider_id, discarded_at=_now(), is_system_default=False),
            delete(llm_config_provider_shares).where(
                llm_config_provider_shares.c.provider_id == provider_id
            ),
            delete(llm_config_provider_defaults).where(
                llm_config_provider_defaults.c.provider_id == provider_id
            ),
        ]
        await self._write(statements, tracking)

    def _update(self, provider_id: UUID, **values: Any) -> Any:
        """Builds an update statement of one provider."""
        return (
            update(llm_config_providers)
            .where(llm_config_providers.c.provider_id == provider_id)
            .values(**values)
        )

    # -- reads --------------------------------------------------------------

    async def get_provider(self, provider_id: UUID) -> ProviderRow | None:
        """Returns a live provider, or ``None``."""
        row = await self._fetch_one(self._live(llm_config_providers.c.provider_id == provider_id))
        return None if row is None else self._provider_row(row)

    async def find_provider_by_name(self, name: str) -> ProviderRow | None:
        """Returns the live provider with the given name, or ``None``."""
        row = await self._fetch_one(self._live(llm_config_providers.c.name == name))
        return None if row is None else self._provider_row(row)

    async def list_providers(
        self,
        owner_user_id: UUID | None = None,
        is_public: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ProviderRow]:
        """Returns live providers, optionally filtered and paged."""
        filters: list[ColumnElement[bool]] = []
        if owner_user_id is not None:
            filters.append(llm_config_providers.c.owner_user_id == owner_user_id)
        if is_public is not None:
            filters.append(llm_config_providers.c.is_public == is_public)
        statement = self._live(*filters).order_by(llm_config_providers.c.name)
        if limit is not None:
            statement = statement.limit(limit)
        if offset:
            statement = statement.offset(offset)
        return [self._provider_row(row) for row in await self._fetch_all(statement)]

    async def list_shares(self, provider_id: UUID) -> list[ProviderShareRow]:
        """Returns the users and groups a provider is shared with."""
        statement = (
            select(llm_config_provider_shares)
            .where(llm_config_provider_shares.c.provider_id == provider_id)
            .order_by(
                llm_config_provider_shares.c.scope,
                llm_config_provider_shares.c.target_id,
            )
        )
        return [
            ProviderShareRow(
                provider_id=as_uuid(row.provider_id),
                scope=row.scope,
                target_id=as_uuid(row.target_id),
            )
            for row in await self._fetch_all(statement)
        ]

    async def list_defaults(self, provider_id: UUID) -> list[ProviderDefaultRow]:
        """Returns the tenants and users a provider is the default of."""
        statement = (
            select(llm_config_provider_defaults)
            .where(llm_config_provider_defaults.c.provider_id == provider_id)
            .order_by(
                llm_config_provider_defaults.c.scope,
                llm_config_provider_defaults.c.target_id,
            )
        )
        return [
            ProviderDefaultRow(
                provider_id=as_uuid(row.provider_id),
                scope=row.scope,
                target_id=as_uuid(row.target_id),
            )
            for row in await self._fetch_all(statement)
        ]

    async def find_default_provider(
        self,
        scope: str,
        target_id: UUID | None = None,
    ) -> ProviderRow | None:
        """Returns the live provider that currently holds the given default."""
        if scope == "system":
            row = await self._fetch_one(
                self._live(llm_config_providers.c.is_system_default.is_(True))
            )
            return None if row is None else self._provider_row(row)
        statement = (
            select(llm_config_providers)
            .join(
                llm_config_provider_defaults,
                llm_config_provider_defaults.c.provider_id == llm_config_providers.c.provider_id,
            )
            .where(
                llm_config_providers.c.discarded_at.is_(None),
                llm_config_provider_defaults.c.scope == scope,
                llm_config_provider_defaults.c.target_id == target_id,
            )
            .order_by(llm_config_providers.c.created_at)
        )
        row = await self._fetch_one(statement)
        return None if row is None else self._provider_row(row)

    async def list_providers_shared_with(
        self,
        user_id: UUID | None = None,
        group_ids: list[UUID] | None = None,
    ) -> list[ProviderRow]:
        """Returns live providers shared with the user or any of the groups."""
        shares = llm_config_provider_shares
        filters: list[ColumnElement[bool]] = []
        if user_id is not None:
            filters.append(and_(shares.c.scope == "user", shares.c.target_id == user_id))
        for group_id in group_ids or []:
            filters.append(and_(shares.c.scope == "group", shares.c.target_id == group_id))
        if not filters:
            return []
        statement = (
            select(llm_config_providers)
            .join(shares, shares.c.provider_id == llm_config_providers.c.provider_id)
            .where(
                llm_config_providers.c.discarded_at.is_(None),
                or_(*filters),
            )
            .distinct()
            .order_by(llm_config_providers.c.name)
        )
        return [self._provider_row(row) for row in await self._fetch_all(statement)]

    def _live(self, *filters: ColumnElement[bool]) -> Select[Any]:
        """Builds a select of live providers narrowed by the given filters."""
        statement = select(llm_config_providers).where(
            llm_config_providers.c.discarded_at.is_(None),
        )
        for condition in filters:
            statement = statement.where(condition)
        return statement

    @staticmethod
    def _provider_row(row: Any) -> ProviderRow:
        """Builds a provider row from a database row."""
        return ProviderRow(
            provider_id=as_uuid(row.provider_id),
            name=row.name,
            kind=row.kind,
            endpoint=row.endpoint,
            credential_ref=row.credential_ref,
            has_inline_credential=bool(row.has_inline_credential),
            default_model=row.default_model,
            options=json.loads(row.options or "{}"),
            owner_user_id=as_uuid(row.owner_user_id),
            tenant_id=None if row.tenant_id is None else as_uuid(row.tenant_id),
            is_public=bool(row.is_public),
            is_system_default=bool(row.is_system_default),
            created_at=row.created_at,
            discarded_at=row.discarded_at,
        )
