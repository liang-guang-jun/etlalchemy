"""Asynchronous SQLAlchemy implementation of the comment read model.

SQLAlchemy Core builds the table definitions and the DML statements; they are
executed on the async engine of
:class:`~etlalchemy._vendor.eventsourcing.asyncio.sqlalchemy.AsyncSQLAlchemyDatastore`, so the view
change and its tracking record share one transaction. The same class serves
SQLite (``aiosqlite``) and PostgreSQL (``psycopg``); only the upsert dialect
differs.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Select, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from etlalchemy._vendor.eventsourcing.asyncio.sqlalchemy import (
    AsyncSQLAlchemyDatastore,
    AsyncSQLAlchemyTrackingRecorder,
)
from etlalchemy.comment.aggregates.types import ThreadStatus
from etlalchemy.comment.projection.tables import (
    comment_comments,
    comment_mentions,
    comment_threads,
    metadata,
)
from etlalchemy.comment.projection.view import (
    CommentRow,
    CommentView,
    ThreadRow,
    as_uuid,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from eventsourcing.persistence import Tracking
    from sqlalchemy import Table


def _mentions_text(mentions: Sequence[UUID]) -> str:
    """Serialises a mention list as a JSON array of UUID strings."""
    return json.dumps([str(mention) for mention in mentions])


def _mentions_from_text(value: str) -> list[UUID]:
    """Parses a mention list stored as a JSON array of UUID strings."""
    return [as_uuid(item) for item in json.loads(value)]


def _live_comment_count(thread_id: UUID) -> Any:
    """Returns the scalar subquery that counts the live comments of a thread."""
    return (
        select(func.count())
        .select_from(comment_comments)
        .where(
            comment_comments.c.thread_id == thread_id,
            comment_comments.c.discarded_at.is_(None),
        )
        .scalar_subquery()
    )


def _with_depths(rows: Sequence[CommentRow]) -> list[CommentRow]:
    """Returns the rows with their depth derived from the parent chain.

    The walk is iterative so a deep reply chain cannot exhaust the recursion
    limit, and a ``seen`` set disconnects a corrupted cycle instead of looping.
    When a parent is not part of the given rows (paging), the depth restarts at
    that breakpoint.
    """
    by_id = {row.comment_id: row for row in rows}
    cache: dict[UUID, int] = {}
    for row in rows:
        chain: list[UUID] = []
        seen: set[UUID] = set()
        current = row.comment_id
        while True:
            if current in cache:
                base = cache[current]
                break
            if current in seen:
                base = 0
                break
            parent_row = by_id.get(current)
            if parent_row is None or parent_row.parent_comment_id is None:
                base = 0
                break
            seen.add(current)
            chain.append(current)
            current = parent_row.parent_comment_id
        for identifier in reversed(chain):
            base += 1
            cache[identifier] = base
        cache.setdefault(row.comment_id, base)
    return [replace(row, depth=cache[row.comment_id]) for row in rows]


class SQLAlchemyCommentView(AsyncSQLAlchemyTrackingRecorder, CommentView):
    """Asynchronous materialised view of the comment aggregates."""

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

    async def register_thread(
        self,
        thread_id: UUID,
        target_type: str,
        target_id: UUID,
        title: str,
        author_user_id: UUID,
        author_tenant_id: UUID | None,
        root_comment_id: UUID,
        body: str,
        mentions: list[UUID],
        created_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Registers a thread together with its root comment."""
        statement = self._insert(comment_threads).values(
            thread_id=thread_id,
            target_type=target_type,
            target_id=target_id,
            title=title,
            status=ThreadStatus.OPEN.value,
            author_user_id=author_user_id,
            author_tenant_id=author_tenant_id,
            comment_count=1,
            last_activity_at=created_at,
            created_at=created_at,
            resolved_at=None,
            resolved_by=None,
            discarded_at=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[comment_threads.c.thread_id],
            set_={
                "target_type": statement.excluded.target_type,
                "target_id": statement.excluded.target_id,
                "title": statement.excluded.title,
                "status": statement.excluded.status,
                "author_user_id": statement.excluded.author_user_id,
                "author_tenant_id": statement.excluded.author_tenant_id,
                "comment_count": 1,
                "last_activity_at": statement.excluded.last_activity_at,
                "created_at": statement.excluded.created_at,
                "discarded_at": statement.excluded.discarded_at,
            },
        )
        statements = [
            statement,
            self._comment_upsert(
                root_comment_id,
                thread_id,
                None,
                author_user_id,
                author_tenant_id,
                body,
                mentions,
                created_at,
            ),
            *self._mention_statements(
                root_comment_id,
                thread_id,
                author_user_id,
                mentions,
                created_at,
            ),
        ]
        await self._write(statements, tracking)

    async def add_comment(
        self,
        comment_id: UUID,
        thread_id: UUID,
        parent_comment_id: UUID | None,
        author_user_id: UUID,
        author_tenant_id: UUID | None,
        body: str,
        mentions: list[UUID],
        created_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Registers a comment and refreshes the thread activity."""
        statements = [
            self._comment_upsert(
                comment_id,
                thread_id,
                parent_comment_id,
                author_user_id,
                author_tenant_id,
                body,
                mentions,
                created_at,
            ),
            delete(comment_mentions).where(comment_mentions.c.comment_id == comment_id),
            *self._mention_statements(
                comment_id,
                thread_id,
                author_user_id,
                mentions,
                created_at,
            ),
            update(comment_threads)
            .where(comment_threads.c.thread_id == thread_id)
            .values(
                comment_count=_live_comment_count(thread_id),
                last_activity_at=created_at,
            ),
        ]
        await self._write(statements, tracking)

    async def edit_comment(
        self,
        comment_id: UUID,
        thread_id: UUID,
        author_user_id: UUID,
        body: str,
        mentions: list[UUID],
        edited_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Replaces the body and mentions of a comment."""
        statements = [
            update(comment_comments)
            .where(
                comment_comments.c.comment_id == comment_id,
                comment_comments.c.thread_id == thread_id,
            )
            .values(
                body=body,
                mentions=_mentions_text(mentions),
                edited_at=edited_at,
            ),
            delete(comment_mentions).where(comment_mentions.c.comment_id == comment_id),
            *self._mention_statements(
                comment_id,
                thread_id,
                author_user_id,
                mentions,
                edited_at,
            ),
        ]
        await self._write(statements, tracking)

    async def discard_comment(
        self,
        comment_id: UUID,
        thread_id: UUID,
        discarded_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Soft-deletes a comment and refreshes the live comment count."""
        statements = [
            update(comment_comments)
            .where(
                comment_comments.c.comment_id == comment_id,
                comment_comments.c.thread_id == thread_id,
            )
            .values(discarded_at=discarded_at),
            update(comment_threads)
            .where(comment_threads.c.thread_id == thread_id)
            .values(comment_count=_live_comment_count(thread_id)),
        ]
        await self._write(statements, tracking)

    async def resolve_thread(
        self,
        thread_id: UUID,
        resolved_by: UUID,
        at: datetime,
        tracking: Tracking,
    ) -> None:
        """Marks a thread as resolved."""
        statement = (
            update(comment_threads)
            .where(comment_threads.c.thread_id == thread_id)
            .values(
                status=ThreadStatus.RESOLVED.value,
                resolved_at=at,
                resolved_by=resolved_by,
                last_activity_at=at,
            )
        )
        await self._write([statement], tracking)

    async def reopen_thread(
        self,
        thread_id: UUID,
        at: datetime,
        tracking: Tracking,
    ) -> None:
        """Reopens a resolved thread."""
        statement = (
            update(comment_threads)
            .where(comment_threads.c.thread_id == thread_id)
            .values(
                status=ThreadStatus.OPEN.value,
                resolved_at=None,
                resolved_by=None,
                last_activity_at=at,
            )
        )
        await self._write([statement], tracking)

    async def discard_thread(
        self,
        thread_id: UUID,
        at: datetime,
        tracking: Tracking,
    ) -> None:
        """Soft-deletes a thread."""
        statement = (
            update(comment_threads)
            .where(comment_threads.c.thread_id == thread_id)
            .values(
                status=ThreadStatus.DISCARDED.value,
                discarded_at=at,
            )
        )
        await self._write([statement], tracking)

    # -- reads --------------------------------------------------------------

    async def get_thread(self, thread_id: UUID) -> ThreadRow | None:
        """Returns one live thread, or ``None``."""
        row = await self._fetch_one(
            select(comment_threads).where(
                comment_threads.c.thread_id == thread_id,
                comment_threads.c.discarded_at.is_(None),
            )
        )
        return None if row is None else self._thread_row(row)

    async def list_threads_for_target(
        self,
        target_type: str,
        target_id: UUID,
        status: str | None = None,
        tenant_id: UUID | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ThreadRow]:
        """Returns the live threads of one target, most recently active first."""
        conditions: list[Any] = [
            comment_threads.c.discarded_at.is_(None),
            comment_threads.c.target_type == target_type,
            comment_threads.c.target_id == target_id,
        ]
        conditions.extend(self._tenant_conditions(tenant_id))
        if status is not None:
            conditions.append(comment_threads.c.status == status)
        statement = self._thread_statement(conditions, limit, offset)
        return [self._thread_row(row) for row in await self._fetch_all(statement)]

    async def list_threads_by_author(
        self,
        author_user_id: UUID,
        status: str | None = None,
        tenant_id: UUID | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ThreadRow]:
        """Returns the live threads started by a user."""
        conditions: list[Any] = [
            comment_threads.c.discarded_at.is_(None),
            comment_threads.c.author_user_id == author_user_id,
        ]
        conditions.extend(self._tenant_conditions(tenant_id))
        if status is not None:
            conditions.append(comment_threads.c.status == status)
        statement = self._thread_statement(conditions, limit, offset)
        return [self._thread_row(row) for row in await self._fetch_all(statement)]

    async def list_threads(
        self,
        status: str | None = None,
        tenant_id: UUID | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ThreadRow]:
        """Returns every live thread, most recently active first."""
        conditions: list[Any] = [comment_threads.c.discarded_at.is_(None)]
        conditions.extend(self._tenant_conditions(tenant_id))
        if status is not None:
            conditions.append(comment_threads.c.status == status)
        statement = self._thread_statement(conditions, limit, offset)
        return [self._thread_row(row) for row in await self._fetch_all(statement)]

    async def list_threads_mentioning(
        self,
        user_id: UUID,
        status: str | None = None,
        tenant_id: UUID | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ThreadRow]:
        """Returns the live threads with a comment that mentions a user."""
        conditions: list[Any] = [
            comment_threads.c.discarded_at.is_(None),
            comment_mentions.c.user_id == user_id,
        ]
        conditions.extend(self._tenant_conditions(tenant_id))
        if status is not None:
            conditions.append(comment_threads.c.status == status)
        statement = (
            select(comment_threads)
            .join(
                comment_mentions,
                comment_mentions.c.thread_id == comment_threads.c.thread_id,
            )
            .where(*conditions)
            .distinct()
            .order_by(
                comment_threads.c.last_activity_at.desc(),
                comment_threads.c.created_at.desc(),
                comment_threads.c.thread_id,
            )
        )
        if limit is not None:
            statement = statement.limit(limit).offset(offset)
        return [self._thread_row(row) for row in await self._fetch_all(statement)]

    async def get_comment(self, comment_id: UUID) -> CommentRow | None:
        """Returns one live comment, or ``None``."""
        row = await self._fetch_one(
            select(comment_comments).where(
                comment_comments.c.comment_id == comment_id,
                comment_comments.c.discarded_at.is_(None),
            )
        )
        return None if row is None else self._comment_row(row)

    async def list_comments(
        self,
        thread_id: UUID,
        include_discarded: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[CommentRow]:
        """Returns the comments of a thread in creation order, with depths."""
        conditions: list[Any] = [comment_comments.c.thread_id == thread_id]
        if not include_discarded:
            conditions.append(comment_comments.c.discarded_at.is_(None))
        statement = (
            select(comment_comments)
            .where(*conditions)
            .order_by(
                comment_comments.c.created_at,
                comment_comments.c.comment_id,
            )
        )
        if limit is not None:
            statement = statement.limit(limit).offset(offset)
        rows = [self._comment_row(row) for row in await self._fetch_all(statement)]
        return _with_depths(rows)

    async def count_threads_for_target(self, target_type: str, target_id: UUID) -> int:
        """Returns the number of live threads of one target."""
        statement = (
            select(func.count())
            .select_from(comment_threads)
            .where(
                comment_threads.c.discarded_at.is_(None),
                comment_threads.c.target_type == target_type,
                comment_threads.c.target_id == target_id,
            )
        )
        async with self.datastore.connection() as conn:
            count: int = (await conn.execute(statement)).scalar_one()
        return count

    # -- helpers ------------------------------------------------------------

    def _comment_upsert(
        self,
        comment_id: UUID,
        thread_id: UUID,
        parent_comment_id: UUID | None,
        author_user_id: UUID,
        author_tenant_id: UUID | None,
        body: str,
        mentions: Sequence[UUID],
        created_at: datetime,
    ) -> Any:
        """Returns the comment upsert used by creation and replay."""
        statement = self._insert(comment_comments).values(
            comment_id=comment_id,
            thread_id=thread_id,
            parent_comment_id=parent_comment_id,
            author_user_id=author_user_id,
            author_tenant_id=author_tenant_id,
            body=body,
            mentions=_mentions_text(mentions),
            created_at=created_at,
            edited_at=None,
            discarded_at=None,
        )
        return statement.on_conflict_do_update(
            index_elements=[comment_comments.c.comment_id],
            set_={
                "thread_id": statement.excluded.thread_id,
                "parent_comment_id": statement.excluded.parent_comment_id,
                "author_user_id": statement.excluded.author_user_id,
                "author_tenant_id": statement.excluded.author_tenant_id,
                "body": statement.excluded.body,
                "mentions": statement.excluded.mentions,
                "created_at": statement.excluded.created_at,
            },
        )

    def _mention_statements(
        self,
        comment_id: UUID,
        thread_id: UUID,
        author_user_id: UUID,
        mentions: Sequence[UUID],
        created_at: datetime,
    ) -> list[Any]:
        """Returns one upsert per mentioned user."""
        statements: list[Any] = []
        for user_id in dict.fromkeys(mentions):
            statement = self._insert(comment_mentions).values(
                comment_id=comment_id,
                thread_id=thread_id,
                user_id=user_id,
                author_user_id=author_user_id,
                created_at=created_at,
            )
            statement = statement.on_conflict_do_update(
                index_elements=[
                    comment_mentions.c.comment_id,
                    comment_mentions.c.user_id,
                ],
                set_={
                    "thread_id": statement.excluded.thread_id,
                    "author_user_id": statement.excluded.author_user_id,
                    "created_at": statement.excluded.created_at,
                },
            )
            statements.append(statement)
        return statements

    def _tenant_conditions(self, tenant_id: UUID | None) -> list[Any]:
        """Returns the tenant filter applied to thread reads."""
        if tenant_id is None:
            return []
        return [
            or_(
                comment_threads.c.author_tenant_id.is_(None),
                comment_threads.c.author_tenant_id == tenant_id,
            )
        ]

    def _thread_statement(
        self,
        conditions: Sequence[Any],
        limit: int | None,
        offset: int,
    ) -> Select[Any]:
        """Returns the standard thread query with ordering and paging."""
        statement = (
            select(comment_threads)
            .where(*conditions)
            .order_by(
                comment_threads.c.last_activity_at.desc(),
                comment_threads.c.created_at.desc(),
                comment_threads.c.thread_id,
            )
        )
        if limit is not None:
            statement = statement.limit(limit).offset(offset)
        return statement

    def _thread_row(self, row: Any) -> ThreadRow:
        """Builds a :class:`ThreadRow` from a database row."""
        return ThreadRow(
            thread_id=as_uuid(row.thread_id),
            target_type=row.target_type,
            target_id=as_uuid(row.target_id),
            title=row.title,
            status=row.status,
            author_user_id=as_uuid(row.author_user_id),
            author_tenant_id=None
            if row.author_tenant_id is None
            else as_uuid(row.author_tenant_id),
            comment_count=row.comment_count,
            last_activity_at=row.last_activity_at,
            created_at=row.created_at,
            resolved_at=row.resolved_at,
            resolved_by=None if row.resolved_by is None else as_uuid(row.resolved_by),
        )

    def _comment_row(self, row: Any) -> CommentRow:
        """Builds a :class:`CommentRow` from a database row."""
        return CommentRow(
            comment_id=as_uuid(row.comment_id),
            thread_id=as_uuid(row.thread_id),
            parent_comment_id=None
            if row.parent_comment_id is None
            else as_uuid(row.parent_comment_id),
            author_user_id=as_uuid(row.author_user_id),
            author_tenant_id=None
            if row.author_tenant_id is None
            else as_uuid(row.author_tenant_id),
            body=row.body,
            mentions=_mentions_from_text(row.mentions),
            created_at=row.created_at,
            edited_at=row.edited_at,
            discarded_at=row.discarded_at,
        )
