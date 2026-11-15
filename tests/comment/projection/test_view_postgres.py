"""Integration tests for the PostgreSQL comment read model.

These tests need a running PostgreSQL database. Point `TEST_DATABASE_URL` (or
`ETLALCHEMY_DSN`) at it, for example:

    docker compose -f docker/docker-compose.yml up -d --wait
    export TEST_DATABASE_URL=postgresql://etlalchemy:etlalchemy@localhost:55432/etlalchemy_test
"""

from __future__ import annotations

import itertools
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore
from eventsourcing.persistence import Tracking

from etlalchemy.comment.projection.sqlalchemy import SQLAlchemyCommentView
from tests.support import async_postgres_url

DSN = os.environ.get("TEST_DATABASE_URL") or os.environ.get("ETLALCHEMY_DSN")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL is not set"),
]

VIEW_TABLES = (
    "comment_threads",
    "comment_comments",
    "comment_mentions",
    "comment_projection_tracking",
)

UPSTREAM = "comment_application"
NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


async def drop_tables(datastore: AsyncSQLAlchemyDatastore) -> None:
    """Drops the comment tables so every test starts from an empty read model."""
    async with datastore.engine.begin() as conn:
        for table in VIEW_TABLES:
            await conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{table}" CASCADE')


@pytest.fixture
async def view() -> AsyncIterator[SQLAlchemyCommentView]:
    """Returns a PostgreSQL view whose tables were just created."""
    datastore = AsyncSQLAlchemyDatastore(async_postgres_url(DSN or ""))
    await drop_tables(datastore)
    comment_view = SQLAlchemyCommentView(
        datastore=datastore,
        tracking_table=datastore.create_tracking_table("comment_projection_tracking"),
    )
    await comment_view.create_table()
    try:
        yield comment_view
    finally:
        await datastore.close()


async def test_the_view_stores_the_whole_thread(view: SQLAlchemyCommentView) -> None:
    """Thread, comments, mentions, depths and counters round-trip through PostgreSQL."""
    counter = itertools.count(1)
    tracking = lambda: Tracking(UPSTREAM, next(counter))  # noqa: E731

    thread_id = uuid4()
    target_id = uuid4()
    author = uuid4()
    mentioned = uuid4()
    root_id = uuid4()
    await view.register_thread(
        thread_id,
        "table",
        target_id,
        "pricing",
        author,
        None,
        root_id,
        "root body",
        [mentioned],
        NOW,
        tracking(),
    )
    first = uuid4()
    second = uuid4()
    await view.add_comment(
        first,
        thread_id,
        None,
        author,
        None,
        "first",
        [],
        NOW + timedelta(minutes=1),
        tracking(),
    )
    await view.add_comment(
        second,
        thread_id,
        first,
        author,
        None,
        "second",
        [],
        NOW + timedelta(minutes=2),
        tracking(),
    )

    thread = await view.get_thread(thread_id)
    assert thread is not None
    assert (thread.title, thread.status, thread.comment_count) == ("pricing", "OPEN", 3)
    assert thread.last_activity_at == NOW + timedelta(minutes=2)

    comments = await view.list_comments(thread_id)
    assert [(row.body, row.depth) for row in comments] == [
        ("root body", 0),
        ("first", 0),
        ("second", 1),
    ]
    assert comments[0].mentions == [mentioned]

    assert [row.thread_id for row in await view.list_threads_mentioning(mentioned)] == [
        thread_id
    ]
    assert [row.thread_id for row in await view.list_threads_for_target("table", target_id)] == [
        thread_id
    ]
    assert await view.list_threads_for_target("schema", target_id) == []
    assert await view.count_threads_for_target("table", target_id) == 1

    await view.edit_comment(
        root_id,
        thread_id,
        author,
        "root edited",
        [],
        NOW + timedelta(minutes=3),
        tracking(),
    )
    edited = await view.get_comment(root_id)
    assert edited is not None
    assert edited.body == "root edited"
    assert edited.mentions == []
    assert await view.list_threads_mentioning(mentioned) == []

    await view.discard_comment(first, thread_id, NOW + timedelta(minutes=4), tracking())
    assert [row.body for row in await view.list_comments(thread_id)] == [
        "root edited",
        "second",
    ]
    assert len(await view.list_comments(thread_id, include_discarded=True)) == 3
    thread = await view.get_thread(thread_id)
    assert thread is not None
    assert thread.comment_count == 2

    await view.resolve_thread(thread_id, author, NOW + timedelta(minutes=5), tracking())
    thread = await view.get_thread(thread_id)
    assert thread is not None
    assert (thread.status, thread.resolved_by) == ("RESOLVED", author)

    await view.reopen_thread(thread_id, NOW + timedelta(minutes=6), tracking())
    thread = await view.get_thread(thread_id)
    assert thread is not None
    assert (thread.status, thread.resolved_at) == ("OPEN", None)

    await view.discard_thread(thread_id, NOW + timedelta(minutes=7), tracking())
    assert await view.get_thread(thread_id) is None
    assert await view.list_threads_for_target("table", target_id) == []
    assert await view.max_tracking_id(UPSTREAM) == next(counter) - 1
