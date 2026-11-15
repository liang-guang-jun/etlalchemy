"""Tests that the comment use cases emit structured logs."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from eventsourcing.persistence import Tracking
from structlog.testing import capture_logs

from etlalchemy.comment.application import CommentApplication
from etlalchemy.comment.projection.sqlalchemy import SQLAlchemyCommentView
from etlalchemy.shared.logging import reset_logging
from tests.comment.support import FakeAuthorization

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
TENANT = uuid4()


@pytest.fixture(autouse=True)
def _fresh_loggers() -> None:
    """Drops cached loggers so ``capture_logs`` sees the application output."""
    reset_logging()


async def test_create_thread_logs_start_and_done(
    comment_app: CommentApplication,
    authorization: FakeAuthorization,
) -> None:
    """Creating a thread logs the command name and the new id."""
    session = authorization.add_session(tenant_id=TENANT)
    target = uuid4()

    with capture_logs() as logs:
        created = await comment_app.create_thread(
            session.session_id,
            "table",
            target,
            "root body",
        )

    assert [entry["event"] for entry in logs] == [
        "comment.thread.create start",
        "comment.thread.create done",
    ]
    assert logs[0]["target_type"] == "table"
    assert logs[0]["target_id"] == str(target)
    assert logs[1]["thread_id"] == str(created.thread_id)


async def test_add_comment_logs_the_depth(
    comment_app: CommentApplication,
    authorization: FakeAuthorization,
) -> None:
    """A reply logs the computed depth once it is stored."""
    session = authorization.add_session(tenant_id=TENANT)
    created = await comment_app.create_thread(session.session_id, "table", uuid4(), "root")

    with capture_logs() as logs:
        reply = await comment_app.add_comment(
            session.session_id,
            created.thread_id,
            "reply",
            created.root_comment_id,
        )

    assert [entry["event"] for entry in logs] == [
        "comment.comment.add start",
        "comment.comment.add done",
    ]
    assert logs[1]["comment_id"] == str(reply.comment_id)
    assert logs[1]["depth"] == 1


async def test_reads_log_at_debug_level(
    comment_app: CommentApplication,
    authorization: FakeAuthorization,
    comment_view: SQLAlchemyCommentView,
) -> None:
    """Reading a thread leaves a debug trail."""
    session = authorization.add_session(tenant_id=TENANT)
    thread_id = uuid4()
    await comment_view.register_thread(
        thread_id,
        "table",
        uuid4(),
        "",
        session.user_id,
        TENANT,
        uuid4(),
        "root body",
        [],
        NOW,
        Tracking("comment_application", 1),
    )

    with capture_logs() as logs:
        await comment_app.get_thread(thread_id, session.session_id)

    assert [entry["event"] for entry in logs] == [
        "comment.thread.get start",
        "comment.thread.get done",
    ]
    assert logs[0]["log_level"] == "debug"
