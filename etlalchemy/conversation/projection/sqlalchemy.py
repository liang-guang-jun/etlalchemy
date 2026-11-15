"""Asynchronous SQLAlchemy implementation of the conversation read model.

SQLAlchemy Core builds the table definitions and the DML statements; they are
executed on the async engine of
:class:`~eventsourcing.asyncio.sqlalchemy.AsyncSQLAlchemyDatastore`, so the view
change and its tracking record still share one transaction. The same class serves
SQLite (``aiosqlite``) and PostgreSQL (``psycopg``); only the upsert dialect
differs.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from eventsourcing.asyncio.sqlalchemy import (
    AsyncSQLAlchemyDatastore,
    AsyncSQLAlchemyTrackingRecorder,
)
from sqlalchemy import Select, delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from etlalchemy.conversation.projection.tables import (
    conversation_approvals,
    conversation_conversations,
    conversation_message_resources,
    conversation_message_tools,
    conversation_messages,
    conversation_runs,
    metadata,
)
from etlalchemy.conversation.projection.view import (
    ApprovalRow,
    ConversationRow,
    ConversationView,
    MessageRow,
    ResourceAccessRow,
    RunRow,
    ToolCallRow,
    as_uuid,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from eventsourcing.persistence import Tracking
    from sqlalchemy import Table


class SQLAlchemyConversationView(AsyncSQLAlchemyTrackingRecorder, ConversationView):
    """Asynchronous materialised view of the conversation aggregate."""

    async def create_table(self) -> None:
        """Creates the tracking table and the view tables if they do not exist."""
        async with self.datastore.transaction() as conn:
            await conn.run_sync(metadata.create_all)
            await conn.run_sync(self.datastore.metadata.create_all)
            await self._ensure_agent_columns(conn)

    async def _ensure_agent_columns(self, conn: Any) -> None:
        """Adds the reasoning and tool preview columns to an older read model."""
        await self._ensure_column(
            conn,
            "conversation_messages",
            "reasoning",
            "TEXT NOT NULL DEFAULT ''",
        )
        await self._ensure_column(
            conn,
            "conversation_message_tools",
            "args_json",
            "TEXT NOT NULL DEFAULT ''",
        )
        await self._ensure_column(
            conn,
            "conversation_message_tools",
            "result_preview",
            "TEXT NOT NULL DEFAULT ''",
        )

    async def _ensure_column(
        self,
        conn: Any,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        """Adds one column when the table predates it.

        Args:
            conn: Connection of the surrounding transaction.
            table: Name of the view table.
            column: Name of the column to add.
            definition: Column type and default, appended to ``ADD COLUMN``.
        """
        if self.datastore.dialect_name == AsyncSQLAlchemyDatastore.SQLITE:
            result = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
            existing = {str(row._mapping["name"]) for row in result.fetchall()}
            if column not in existing:
                await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            return
        await conn.exec_driver_sql(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}"
        )

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

    async def register_conversation(
        self,
        conversation_id: UUID,
        user_id: UUID,
        tenant_id: UUID | None,
        title: str,
        active_llm_provider_id: UUID | None,
        created_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Registers a conversation, clearing a previous discarded marker."""
        statement = self._insert(conversation_conversations).values(
            conversation_id=conversation_id,
            user_id=user_id,
            tenant_id=tenant_id,
            title=title,
            status="OPEN",
            active_llm_provider_id=active_llm_provider_id,
            message_count=0,
            run_count=0,
            created_at=created_at,
            last_activity_at=created_at,
            discarded_at=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[conversation_conversations.c.conversation_id],
            set_={
                "user_id": statement.excluded.user_id,
                "tenant_id": statement.excluded.tenant_id,
                "title": statement.excluded.title,
                "status": statement.excluded.status,
                "active_llm_provider_id": statement.excluded.active_llm_provider_id,
                "created_at": statement.excluded.created_at,
                "last_activity_at": statement.excluded.last_activity_at,
                "discarded_at": statement.excluded.discarded_at,
            },
        )
        await self._write([statement], tracking)

    async def rename_conversation(
        self,
        conversation_id: UUID,
        title: str,
        tracking: Tracking,
    ) -> None:
        """Changes the title of a conversation."""
        await self._write([self._touch(conversation_id, title=title)], tracking)

    async def switch_provider(
        self,
        conversation_id: UUID,
        provider_id: UUID | None,
        tracking: Tracking,
    ) -> None:
        """Changes the LLM provider a conversation uses."""
        statement = update(conversation_conversations).where(
            conversation_conversations.c.conversation_id == conversation_id
        )
        await self._write(
            [statement.values(active_llm_provider_id=provider_id)],
            tracking,
        )

    async def append_message(
        self,
        message_id: UUID,
        conversation_id: UUID,
        role: str,
        content: str,
        created_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Registers a message without a trace and bumps the activity pointer."""
        insert = self._insert(conversation_messages).values(
            message_id=message_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            interrupted=False,
            input_tokens=0,
            output_tokens=0,
            created_at=created_at,
            discarded_at=None,
        )
        statement = insert.on_conflict_do_update(
            index_elements=[conversation_messages.c.message_id],
            set_={
                "content": insert.excluded.content,
                "role": insert.excluded.role,
                "discarded_at": insert.excluded.discarded_at,
            },
        )
        await self._write(
            [
                statement,
                self._bump_activity(conversation_id, created_at, messages=1),
            ],
            tracking,
        )

    async def edit_message(
        self,
        conversation_id: UUID,
        message_id: UUID,
        content: str,
        removed_message_ids: tuple[UUID, ...],
        removed_run_ids: tuple[UUID, ...],
        edited_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Rewrites a user message and soft-deletes everything after it."""
        statements: list[Any] = [
            update(conversation_messages)
            .where(conversation_messages.c.message_id == message_id)
            .values(content=content),
        ]
        if removed_message_ids:
            statements.append(
                update(conversation_messages)
                .where(conversation_messages.c.message_id.in_(removed_message_ids))
                .values(discarded_at=edited_at),
            )
            statements.append(
                delete(conversation_message_tools).where(
                    conversation_message_tools.c.message_id.in_(removed_message_ids),
                ),
            )
            statements.append(
                delete(conversation_message_resources).where(
                    conversation_message_resources.c.message_id.in_(removed_message_ids),
                ),
            )
        if removed_run_ids:
            statements.append(
                delete(conversation_approvals).where(
                    conversation_approvals.c.run_id.in_(removed_run_ids),
                ),
            )
            statements.append(
                delete(conversation_runs).where(
                    conversation_runs.c.run_id.in_(removed_run_ids),
                ),
            )
        statements.append(
            self._bump_activity(
                conversation_id,
                edited_at,
                messages=-len(removed_message_ids),
                runs=-len(removed_run_ids),
            ),
        )
        await self._write(statements, tracking)

    async def complete_message(
        self,
        message_id: UUID,
        conversation_id: UUID,
        role: str,
        content: str,
        interrupted: bool,
        input_tokens: int,
        output_tokens: int,
        resources: list[ResourceAccessRow],
        tools: list[ToolCallRow],
        created_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Registers an assistant message with its whole trace."""
        insert = self._insert(conversation_messages).values(
            message_id=message_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            interrupted=interrupted,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            created_at=created_at,
            discarded_at=None,
        )
        statement = insert.on_conflict_do_update(
            index_elements=[conversation_messages.c.message_id],
            set_={
                "content": insert.excluded.content,
                "interrupted": insert.excluded.interrupted,
                "input_tokens": insert.excluded.input_tokens,
                "output_tokens": insert.excluded.output_tokens,
                "discarded_at": insert.excluded.discarded_at,
            },
        )
        statements: list[Any] = [statement]
        statements.extend(
            self._insert(conversation_message_resources).values(
                message_id=message_id,
                ordinal=index,
                uri=resource.uri,
                size_bytes=resource.size_bytes,
                mime_type=resource.mime_type,
                read_at=resource.read_at,
            )
            for index, resource in enumerate(resources)
        )
        statements.extend(
            self._insert(conversation_message_tools).values(
                message_id=message_id,
                ordinal=index,
                tool=call.tool,
                args_hash=call.args_hash,
                status=call.status,
                duration_ms=call.duration_ms,
                error_code=call.error_code,
                args_json=call.args_json,
                result_preview=call.result_preview,
            )
            for index, call in enumerate(tools)
        )
        statements.append(self._bump_activity(conversation_id, created_at, messages=1))
        await self._write(statements, tracking)

    async def record_reasoning(
        self,
        message_id: UUID,
        reasoning: str,
        tracking: Tracking,
    ) -> None:
        """Stores the thinking of an already registered assistant message."""
        statement = (
            update(conversation_messages)
            .where(conversation_messages.c.message_id == message_id)
            .values(reasoning=reasoning)
        )
        await self._write([statement], tracking)

    async def start_run(
        self,
        run_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
        started_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Registers a running agent run."""
        insert = self._insert(conversation_runs).values(
            run_id=run_id,
            conversation_id=conversation_id,
            message_id=message_id,
            status="running",
            started_at=started_at,
            finished_at=None,
            error=None,
        )
        statement = insert.on_conflict_do_update(
            index_elements=[conversation_runs.c.run_id],
            set_={
                "message_id": insert.excluded.message_id,
                "status": insert.excluded.status,
                "started_at": insert.excluded.started_at,
                "finished_at": insert.excluded.finished_at,
                "error": insert.excluded.error,
            },
        )
        await self._write(
            [statement, self._bump_activity(conversation_id, started_at, runs=1)],
            tracking,
        )

    async def request_approval(
        self,
        approval_id: UUID,
        run_id: UUID,
        conversation_id: UUID,
        tool: str,
        args_hash: str,
        reason: str,
        requested_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Registers a pending approval."""
        insert = self._insert(conversation_approvals).values(
            approval_id=approval_id,
            run_id=run_id,
            conversation_id=conversation_id,
            tool=tool,
            args_hash=args_hash,
            reason=reason,
            status="pending",
            requested_at=requested_at,
            decided_by=None,
            decided_at=None,
        )
        statement = insert.on_conflict_do_update(
            index_elements=[conversation_approvals.c.approval_id],
            set_={
                "tool": insert.excluded.tool,
                "args_hash": insert.excluded.args_hash,
                "reason": insert.excluded.reason,
                "status": insert.excluded.status,
            },
        )
        await self._write(
            [statement, self._bump_activity(conversation_id, requested_at)],
            tracking,
        )

    async def decide_approval(
        self,
        approval_id: UUID,
        approved: bool,
        decided_by: UUID,
        decided_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Finalises a pending approval."""
        statement = (
            update(conversation_approvals)
            .where(conversation_approvals.c.approval_id == approval_id)
            .values(
                status="approved" if approved else "denied",
                decided_by=decided_by,
                decided_at=decided_at,
            )
        )
        await self._write([statement], tracking)

    async def finish_run(
        self,
        run_id: UUID,
        status: str,
        finished_at: datetime,
        error: str | None,
        tracking: Tracking,
    ) -> None:
        """Finalises a run."""
        statement = (
            update(conversation_runs)
            .where(conversation_runs.c.run_id == run_id)
            .values(status=status, finished_at=finished_at, error=error)
        )
        await self._write([statement], tracking)

    async def discard_conversation(
        self,
        conversation_id: UUID,
        discarded_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Soft-deletes a conversation and cascades to its messages."""
        statements: list[Any] = [
            update(conversation_conversations)
            .where(conversation_conversations.c.conversation_id == conversation_id)
            .values(status="DISCARDED", discarded_at=discarded_at),
            update(conversation_messages)
            .where(conversation_messages.c.conversation_id == conversation_id)
            .values(discarded_at=discarded_at),
        ]
        await self._write(statements, tracking)

    def _touch(self, conversation_id: UUID, **values: Any) -> Any:
        """Builds an update of one conversation."""
        return (
            update(conversation_conversations)
            .where(conversation_conversations.c.conversation_id == conversation_id)
            .values(**values)
        )

    def _bump_activity(
        self,
        conversation_id: UUID,
        at: datetime,
        messages: int = 0,
        runs: int = 0,
    ) -> Any:
        """Builds an update that advances the activity pointer and the counters."""
        return self._touch(
            conversation_id,
            last_activity_at=at,
            message_count=conversation_conversations.c.message_count + messages,
            run_count=conversation_conversations.c.run_count + runs,
        )

    # -- reads --------------------------------------------------------------

    async def get_conversation(self, conversation_id: UUID) -> ConversationRow | None:
        """Returns a live conversation, or ``None``."""
        row = await self._fetch_one(
            select(conversation_conversations).where(
                conversation_conversations.c.conversation_id == conversation_id,
                conversation_conversations.c.discarded_at.is_(None),
            )
        )
        return None if row is None else self._conversation_row(row)

    async def list_conversations(
        self,
        user_id: UUID,
        tenant_id: UUID | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ConversationRow]:
        """Returns live conversations of a user, most recently active first."""
        statement = select(conversation_conversations).where(
            conversation_conversations.c.user_id == user_id,
            conversation_conversations.c.discarded_at.is_(None),
        )
        if tenant_id is not None:
            statement = statement.where(
                conversation_conversations.c.tenant_id == tenant_id,
            )
        statement = statement.order_by(
            conversation_conversations.c.last_activity_at.desc(),
            conversation_conversations.c.conversation_id,
        )
        if limit is not None:
            statement = statement.limit(limit)
        if offset:
            statement = statement.offset(offset)
        return [self._conversation_row(row) for row in await self._fetch_all(statement)]

    async def list_messages(
        self,
        conversation_id: UUID,
        limit: int | None = None,
        offset: int = 0,
        newest_first: bool = False,
    ) -> list[MessageRow]:
        """Returns the messages of a conversation in creation order."""
        order = (
            (
                conversation_messages.c.created_at.desc(),
                conversation_messages.c.message_id.desc(),
            )
            if newest_first
            else (
                conversation_messages.c.created_at,
                conversation_messages.c.message_id,
            )
        )
        statement = (
            select(conversation_messages)
            .where(
                conversation_messages.c.conversation_id == conversation_id,
                conversation_messages.c.discarded_at.is_(None),
            )
            .order_by(*order)
        )
        if limit is not None:
            statement = statement.limit(limit)
        if offset:
            statement = statement.offset(offset)
        rows = list(await self._fetch_all(statement))
        if newest_first:
            rows.reverse()
        message_ids = [as_uuid(row.message_id) for row in rows]
        resources = await self._traces(conversation_message_resources, message_ids)
        tools = await self._traces(conversation_message_tools, message_ids)
        return [
            self._message_row(
                row,
                resources.get(as_uuid(row.message_id), []),
                tools.get(as_uuid(row.message_id), []),
            )
            for row in rows
        ]

    async def get_message(self, message_id: UUID) -> MessageRow | None:
        """Returns one message, or ``None``."""
        row = await self._fetch_one(
            select(conversation_messages).where(
                conversation_messages.c.message_id == message_id,
                conversation_messages.c.discarded_at.is_(None),
            )
        )
        if row is None:
            return None
        resources = await self._traces(conversation_message_resources, [message_id])
        tools = await self._traces(conversation_message_tools, [message_id])
        return self._message_row(
            row,
            resources.get(message_id, []),
            tools.get(message_id, []),
        )

    async def count_messages(self, conversation_id: UUID) -> int:
        """Returns the number of live messages of a conversation."""
        rows = await self._fetch_all(
            select(conversation_messages.c.message_id).where(
                conversation_messages.c.conversation_id == conversation_id,
                conversation_messages.c.discarded_at.is_(None),
            )
        )
        return len(rows)

    async def get_run(self, run_id: UUID) -> RunRow | None:
        """Returns one run with its approvals, or ``None``."""
        row = await self._fetch_one(
            select(conversation_runs).where(conversation_runs.c.run_id == run_id)
        )
        if row is None:
            return None
        approvals = await self._fetch_all(
            select(conversation_approvals)
            .where(conversation_approvals.c.run_id == run_id)
            .order_by(conversation_approvals.c.requested_at)
        )
        return self._run_row(row, [self._approval_row(item) for item in approvals])

    async def list_runs(self, conversation_id: UUID) -> list[RunRow]:
        """Returns the runs of a conversation in start order."""
        rows = await self._fetch_all(
            select(conversation_runs)
            .where(conversation_runs.c.conversation_id == conversation_id)
            .order_by(conversation_runs.c.started_at, conversation_runs.c.run_id)
        )
        if not rows:
            return []
        approvals = await self._fetch_all(
            select(conversation_approvals)
            .where(conversation_approvals.c.conversation_id == conversation_id)
            .order_by(conversation_approvals.c.requested_at)
        )
        grouped: dict[UUID, list[ApprovalRow]] = {}
        for item in approvals:
            grouped.setdefault(as_uuid(item.run_id), []).append(self._approval_row(item))
        return [self._run_row(row, grouped.get(as_uuid(row.run_id), [])) for row in rows]

    async def list_pending_approvals(self, conversation_id: UUID) -> list[ApprovalRow]:
        """Returns the approvals of a conversation that still wait for a decision.

        Only approvals of a run that is still running count: a run that finished
        can leave a ``pending`` row behind (the graph answered a second interrupt
        with the first decision), and offering it would only earn a 409.
        """
        running = select(conversation_runs.c.run_id).where(
            conversation_runs.c.conversation_id == conversation_id,
            conversation_runs.c.status == "running",
        )
        rows = await self._fetch_all(
            select(conversation_approvals)
            .where(
                conversation_approvals.c.conversation_id == conversation_id,
                conversation_approvals.c.status == "pending",
                conversation_approvals.c.run_id.in_(running),
            )
            .order_by(conversation_approvals.c.requested_at)
        )
        return [self._approval_row(item) for item in rows]

    async def _traces(self, table: Table, message_ids: list[UUID]) -> dict[UUID, list[Any]]:
        """Groups the trace rows of the given messages by message id."""
        if not message_ids:
            return {}
        rows = await self._fetch_all(
            select(table)
            .where(table.c.message_id.in_(message_ids))
            .order_by(table.c.message_id, table.c.ordinal)
        )
        grouped: dict[UUID, list[Any]] = {}
        for row in rows:
            grouped.setdefault(as_uuid(row.message_id), []).append(row)
        return grouped

    @staticmethod
    def _conversation_row(row: Any) -> ConversationRow:
        """Builds a conversation row from a database row."""
        return ConversationRow(
            conversation_id=as_uuid(row.conversation_id),
            user_id=as_uuid(row.user_id),
            tenant_id=None if row.tenant_id is None else as_uuid(row.tenant_id),
            title=row.title,
            status=row.status,
            active_llm_provider_id=(
                None if row.active_llm_provider_id is None else as_uuid(row.active_llm_provider_id)
            ),
            message_count=int(row.message_count),
            run_count=int(row.run_count),
            created_at=row.created_at,
            last_activity_at=row.last_activity_at,
            discarded_at=row.discarded_at,
        )

    @staticmethod
    def _message_row(
        row: Any,
        resources: list[Any],
        tools: list[Any],
    ) -> MessageRow:
        """Builds a message row from a database row and its traces."""
        return MessageRow(
            message_id=as_uuid(row.message_id),
            conversation_id=as_uuid(row.conversation_id),
            role=row.role,
            content=row.content,
            interrupted=bool(row.interrupted),
            input_tokens=int(row.input_tokens),
            output_tokens=int(row.output_tokens),
            created_at=row.created_at,
            resources=[
                ResourceAccessRow(
                    uri=item.uri,
                    size_bytes=int(item.size_bytes),
                    mime_type=item.mime_type,
                    read_at=item.read_at,
                )
                for item in resources
            ],
            tools=[
                ToolCallRow(
                    tool=item.tool,
                    args_hash=item.args_hash,
                    status=item.status,
                    duration_ms=int(item.duration_ms),
                    error_code=item.error_code,
                    args_json=item.args_json,
                    result_preview=item.result_preview,
                )
                for item in tools
            ],
            reasoning=row.reasoning,
        )

    @staticmethod
    def _approval_row(row: Any) -> ApprovalRow:
        """Builds an approval row from a database row."""
        return ApprovalRow(
            approval_id=as_uuid(row.approval_id),
            run_id=as_uuid(row.run_id),
            conversation_id=as_uuid(row.conversation_id),
            tool=row.tool,
            args_hash=row.args_hash,
            reason=row.reason,
            status=row.status,
            requested_at=row.requested_at,
            decided_by=None if row.decided_by is None else as_uuid(row.decided_by),
            decided_at=row.decided_at,
        )

    @staticmethod
    def _run_row(row: Any, approvals: list[ApprovalRow]) -> RunRow:
        """Builds a run row from a database row and its approvals."""
        return RunRow(
            run_id=as_uuid(row.run_id),
            conversation_id=as_uuid(row.conversation_id),
            message_id=as_uuid(row.message_id),
            status=row.status,
            started_at=row.started_at,
            finished_at=row.finished_at,
            error=row.error,
            approvals=approvals,
        )
