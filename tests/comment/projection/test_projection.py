"""Tests for the comment projection runner."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore

from etlalchemy.comment.aggregates.errors import UnknownThreadError
from etlalchemy.comment.application import CommentApplication
from etlalchemy.comment.projection.projection import run_comment_projection
from etlalchemy.comment.projection.sqlalchemy import SQLAlchemyCommentView
from etlalchemy.comment.projection.tables import metadata as view_metadata
from tests.comment.support import FakeAuthorization, FakeTargetLookup
from tests.support import async_env, sqlite_url

TENANT = uuid4()


@pytest.fixture
def events_url(tmp_path: Path) -> str:
    """Returns the SQLite URL used by the event store and the view."""
    return sqlite_url(tmp_path / "events.db")


@pytest.fixture
def env(events_url: str) -> dict[str, str]:
    """Returns an environment backed by a temporary SQLite event store."""
    return async_env(events_url)


async def write_thread(
    env: dict[str, str],
    events_url: str,
    authorization: FakeAuthorization,
    target_lookup: FakeTargetLookup,
) -> tuple[UUID, UUID, UUID, UUID, UUID, int]:
    """Writes a thread with a reply chain and returns the ids and last notification."""
    datastore = AsyncSQLAlchemyDatastore(events_url)
    view = SQLAlchemyCommentView(
        datastore=datastore,
        tracking_table=datastore.create_tracking_table("comment_projection_tracking"),
    )
    await view.create_table()
    session = authorization.add_session(tenant_id=TENANT)
    mentioned = authorization.add_session(tenant_id=TENANT).user_id
    target = target_lookup.add("table", uuid4())
    try:
        async with CommentApplication(
            view=view,
            iam=authorization,
            target_lookup=target_lookup,
            env=env,
        ) as app:
            created = await app.create_thread(
                session.session_id,
                "table",
                target,
                "root body",
                mentions=[mentioned],
                title="pricing",
            )
            first = await app.add_comment(
                session.session_id,
                created.thread_id,
                "first reply",
                created.root_comment_id,
            )
            second = await app.add_comment(
                session.session_id,
                created.thread_id,
                "second reply",
                first.comment_id,
            )
            discarded = await app.add_comment(
                session.session_id,
                created.thread_id,
                "discard me",
                created.root_comment_id,
            )
            await app.edit_comment(
                session.session_id,
                created.thread_id,
                first.comment_id,
                body="first edited",
                mentions=[mentioned],
            )
            await app.discard_comment(
                session.session_id,
                created.thread_id,
                discarded.comment_id,
            )
            last = await app.recorder.max_notification_id()
    finally:
        await datastore.close()
    assert last is not None
    return (
        created.thread_id,
        created.root_comment_id,
        first.comment_id,
        second.comment_id,
        mentioned,
        last,
    )


async def test_projection_materialises_the_thread(
    env: dict[str, str],
    events_url: str,
    authorization: FakeAuthorization,
    target_lookup: FakeTargetLookup,
) -> None:
    """The runner keeps the thread, its comments and its mentions in step."""
    thread_id, root_id, first_id, second_id, mentioned, last = await write_thread(
        env,
        events_url,
        authorization,
        target_lookup,
    )

    async with run_comment_projection(env) as runner:
        await runner.wait(last, timeout=5.0)
        view: Any = runner.view

        thread = await view.get_thread(thread_id)
        assert thread is not None
        assert thread.title == "pricing"
        assert thread.status == "OPEN"
        assert thread.comment_count == 3
        assert thread.author_tenant_id == TENANT

        comments = await view.list_comments(thread_id)
        assert [(row.comment_id, row.body, row.depth) for row in comments] == [
            (root_id, "root body", 0),
            (first_id, "first edited", 1),
            (second_id, "second reply", 2),
        ]
        assert comments[1].mentions == [mentioned]
        assert comments[1].edited_at is not None

        with_discarded = await view.list_comments(thread_id, include_discarded=True)
        assert len(with_discarded) == 4
        assert any(row.discarded_at is not None for row in with_discarded)

        mentioning = await view.list_threads_mentioning(mentioned)
        assert [row.thread_id for row in mentioning] == [thread_id]

        assert await view.max_tracking_id("comment_application") == last


async def test_projection_follows_the_status_transitions(
    env: dict[str, str],
    events_url: str,
    authorization: FakeAuthorization,
    target_lookup: FakeTargetLookup,
) -> None:
    """Resolve, reopen and discard are projected as they happen."""
    thread_id, _, _, _, _, last = await write_thread(
        env,
        events_url,
        authorization,
        target_lookup,
    )
    session = next(iter(authorization.sessions.values()))

    async with run_comment_projection(env) as runner:
        await runner.wait(last, timeout=5.0)
        async with CommentApplication(
            view=runner.view,
            iam=authorization,
            target_lookup=target_lookup,
            env=env,
        ) as app:
            await app.resolve_thread(session.session_id, thread_id)
            resolved = await app.recorder.max_notification_id()
            await runner.wait(resolved, timeout=5.0)
            row = await runner.view.get_thread(thread_id)
            assert row is not None
            assert row.status == "RESOLVED"
            assert row.resolved_by == session.user_id
            assert row.resolved_at is not None

            await app.reopen_thread(session.session_id, thread_id)
            reopened = await app.recorder.max_notification_id()
            await runner.wait(reopened, timeout=5.0)
            row = await runner.view.get_thread(thread_id)
            assert row is not None
            assert row.status == "OPEN"
            assert row.resolved_at is None

            await app.discard_thread(session.session_id, thread_id)
            discarded = await app.recorder.max_notification_id()
            await runner.wait(discarded, timeout=5.0)
            assert await runner.view.get_thread(thread_id) is None
            assert await runner.view.list_threads_for_target("table", row.target_id) == []


async def test_application_reads_use_the_projected_view(
    env: dict[str, str],
    events_url: str,
    authorization: FakeAuthorization,
    target_lookup: FakeTargetLookup,
) -> None:
    """Reads through the application filter by tenant and cap the depth."""
    thread_id, _, _, _, _, last = await write_thread(
        env,
        events_url,
        authorization,
        target_lookup,
    )
    session = next(iter(authorization.sessions.values()))
    other = authorization.add_session(tenant_id=uuid4())

    async with run_comment_projection(env) as runner:
        await runner.wait(last, timeout=5.0)
        async with CommentApplication(
            view=runner.view,
            iam=authorization,
            target_lookup=target_lookup,
            env=env,
        ) as app:
            thread = await app.get_thread(thread_id, session.session_id)
            assert thread.thread.thread_id == thread_id
            assert [row.depth for row in thread.comments] == [0, 1, 2]

            with pytest.raises(UnknownThreadError):
                await app.get_thread(thread_id, other.session_id)

            flattened = await app.list_comments(
                thread_id,
                session.session_id,
                flatten_after=1,
            )
            assert [row.depth for row in flattened] == [0, 1, 1]

            visible = await app.list_threads(
                session.session_id,
                target_type="table",
                target_id=thread.thread.target_id,
            )
            assert [row.thread_id for row in visible] == [thread_id]


async def test_rebuilding_the_view_replays_the_whole_event_stream(
    env: dict[str, str],
    events_url: str,
    authorization: FakeAuthorization,
    target_lookup: FakeTargetLookup,
) -> None:
    """Dropping the read model and replaying restores the same state."""
    thread_id, _, _, _, _, last = await write_thread(
        env,
        events_url,
        authorization,
        target_lookup,
    )
    async with run_comment_projection(env) as runner:
        await runner.wait(last, timeout=5.0)
        before: Any = runner.view
        expected = await before.list_comments(thread_id)

    await _reset_read_model(events_url)

    async with run_comment_projection(env) as runner:
        await runner.wait(last, timeout=5.0)
        assert await runner.view.list_comments(thread_id) == expected


async def _reset_read_model(url: str) -> None:
    """Drops the read model, keeping the event store, and recreates its tables."""
    datastore = AsyncSQLAlchemyDatastore(url)
    try:
        view = SQLAlchemyCommentView(
            datastore=datastore,
            tracking_table=datastore.create_tracking_table(
                "comment_projection_tracking",
            ),
        )
        async with datastore.transaction() as conn:
            await conn.run_sync(view_metadata.drop_all)
            await conn.execute(
                sa.text("DROP TABLE IF EXISTS comment_projection_tracking"),
            )
        await view.create_table()
    finally:
        await datastore.close()
