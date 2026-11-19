"""Tests of the read-model migration of an older conversation database."""

from __future__ import annotations

from etlalchemy.conversation.projection.sqlalchemy import SQLAlchemyConversationView
from eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore


async def test_an_older_view_gains_the_reasoning_and_preview_columns(
    datastore: AsyncSQLAlchemyDatastore,
) -> None:
    """``create_table`` adds the new columns instead of failing on an old table."""
    async with datastore.transaction() as conn:
        await conn.exec_driver_sql(
            "CREATE TABLE conversation_messages ("
            "message_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, "
            "role TEXT NOT NULL, content TEXT NOT NULL, interrupted BOOLEAN NOT NULL, "
            "input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, "
            "created_at TEXT NOT NULL, discarded_at TEXT)"
        )
        await conn.exec_driver_sql(
            "CREATE TABLE conversation_message_tools ("
            "message_id TEXT NOT NULL, ordinal INTEGER NOT NULL, tool TEXT NOT NULL, "
            "args_hash TEXT NOT NULL, status TEXT NOT NULL, duration_ms INTEGER NOT NULL, "
            "error_code TEXT, PRIMARY KEY (message_id, ordinal))"
        )

    view = SQLAlchemyConversationView(
        datastore=datastore,
        tracking_table=datastore.create_tracking_table("conversation_projection_tracking"),
    )
    await view.create_table()

    async with datastore.connection() as conn:
        columns = await conn.exec_driver_sql("PRAGMA table_info(conversation_messages)")
        names = {str(row._mapping["name"]) for row in columns.fetchall()}
        tool_columns = await conn.exec_driver_sql(
            "PRAGMA table_info(conversation_message_tools)"
        )
        tool_names = {str(row._mapping["name"]) for row in tool_columns.fetchall()}

    assert "reasoning" in names
    assert {"args_json", "result_preview"} <= tool_names
