"""Tests for the comment application use cases."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from etlalchemy.comment.aggregates.errors import (
    CommentAuthorMismatchError,
    DuplicateThreadError,
    ThreadFullError,
    UnknownCommentError,
    UnknownMentionedUserError,
    UnknownTargetError,
    UnknownTargetTypeError,
    UnknownThreadError,
)
from etlalchemy.comment.application import CommentApplication, CommentOptions
from etlalchemy.comment.projection.sqlalchemy import SQLAlchemyCommentView
from etlalchemy.iam.aggregates.errors import AuthenticationError, PermissionDeniedError
from eventsourcing.persistence import Tracking

from tests.comment.support import FakeAuthorization, FakeTargetLookup

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
TENANT = uuid4()

BuildApp = Callable[[CommentOptions | None], Any]


async def start_thread(
    app: CommentApplication,
    authorization: FakeAuthorization,
    *,
    tenant_id: UUID | None = TENANT,
    target_id: UUID | None = None,
    body: str = "root body",
    title: str = "",
) -> tuple[UUID, UUID, UUID]:
    """Starts a thread for a table target and returns thread, root and target ids."""
    session = authorization.add_session(tenant_id=tenant_id)
    target = target_id or uuid4()
    created = await app.create_thread(
        session.session_id,
        "table",
        target,
        body,
        title=title,
    )
    return created.thread_id, created.root_comment_id, target


async def test_create_thread_stores_the_root_comment(
    comment_app: CommentApplication,
    authorization: FakeAuthorization,
) -> None:
    """A new thread is OPEN and carries the stripped root comment."""
    thread_id, root_id, target = await start_thread(
        comment_app,
        authorization,
        body="  root body  ",
        title="  pricing  ",
    )

    thread = await comment_app.repository.get(thread_id)
    assert thread.target_type == "table"
    assert thread.target_id == target
    assert thread.title == "pricing"
    assert thread.status == "OPEN"
    assert thread.comment_count == 1
    assert thread.comments[root_id].body == "root body"


async def test_create_thread_rejects_an_unregistered_target_type(
    comment_app: CommentApplication,
    authorization: FakeAuthorization,
) -> None:
    """Only the target types of the registry are accepted on the write path."""
    session = authorization.add_session()

    with pytest.raises(UnknownTargetTypeError):
        await comment_app.create_thread(session.session_id, "diagram", uuid4(), "body")


async def test_create_thread_checks_the_mentioned_users(
    comment_app: CommentApplication,
    authorization: FakeAuthorization,
) -> None:
    """A mention must name an active user."""
    session = authorization.add_session()

    with pytest.raises(UnknownMentionedUserError):
        await comment_app.create_thread(session.session_id, "table", uuid4(), "body", mentions=[uuid4()])

    mentioned = authorization.add_session().user_id
    created = await comment_app.create_thread(
        session.session_id,
        "table",
        uuid4(),
        "body",
        mentions=[mentioned, mentioned],
    )
    thread = await comment_app.repository.get(created.thread_id)
    assert thread.comments[created.root_comment_id].mentions == (mentioned,)


async def test_target_existence_is_optional(
    build_app: BuildApp,
    authorization: FakeAuthorization,
    target_lookup: FakeTargetLookup,
) -> None:
    """Enabling the check rejects a target the lookup does not know."""
    session = authorization.add_session()
    target = uuid4()

    async with build_app(CommentOptions(validate_target_exists=True)) as app:
        with pytest.raises(UnknownTargetError):
            await app.create_thread(session.session_id, "table", target, "body")

        target_lookup.add("table", target)
        await app.create_thread(session.session_id, "table", target, "body")


async def test_only_one_thread_per_target_when_disallowed(
    build_app: BuildApp,
    authorization: FakeAuthorization,
    comment_view: SQLAlchemyCommentView,
) -> None:
    """The duplicate check reads the comment view."""
    session = authorization.add_session(tenant_id=TENANT)
    target = uuid4()
    await comment_view.register_thread(
        uuid4(),
        "table",
        target,
        "",
        session.user_id,
        TENANT,
        uuid4(),
        "existing",
        [],
        NOW,
        Tracking("comment_application", 1),
    )

    async with build_app(CommentOptions(allow_multiple_threads=False)) as app:
        with pytest.raises(DuplicateThreadError):
            await app.create_thread(session.session_id, "table", target, "body")


async def test_add_comment_reports_the_depth_without_a_warning(
    comment_app: CommentApplication,
    authorization: FakeAuthorization,
) -> None:
    """The default soft limit of 0 disables the advisory warning."""
    session = authorization.add_session(tenant_id=TENANT)
    created = await comment_app.create_thread(session.session_id, "table", uuid4(), "root")
    parent = created.root_comment_id
    for expected in (1, 2, 3):
        comment = await comment_app.add_comment(
            session.session_id,
            created.thread_id,
            "reply",
            parent_comment_id=parent,
        )
        assert comment.depth == expected
        assert comment.depth_warning is None
        parent = comment.comment_id


async def test_soft_depth_warning_is_advisory(
    build_app: BuildApp,
    authorization: FakeAuthorization,
) -> None:
    """A reply beyond the soft limit is saved and carries a rendered warning."""
    session = authorization.add_session(tenant_id=TENANT)

    async with build_app(CommentOptions(soft_max_reply_depth=8)) as app:
        created = await app.create_thread(session.session_id, "table", uuid4(), "root")
        parent = created.root_comment_id
        for _ in range(8):
            parent = (
                await app.add_comment(session.session_id, created.thread_id, "reply", parent)
            ).comment_id
        eighth = await app.add_comment(session.session_id, created.thread_id, "reply", parent)
        assert eighth.depth == 9
        assert eighth.depth_warning is not None
        assert "9" in eighth.depth_warning
        assert "8" in eighth.depth_warning

        thread = await app.repository.get(created.thread_id)
        assert thread.comment_count == 10


async def test_thread_cap_rejects_the_extra_comment(
    build_app: BuildApp,
    authorization: FakeAuthorization,
) -> None:
    """The hard cap counts the root comment and the discarded ones."""
    session = authorization.add_session(tenant_id=TENANT)

    async with build_app(CommentOptions(max_comments_per_thread=3)) as app:
        created = await app.create_thread(session.session_id, "table", uuid4(), "root")
        await app.add_comment(session.session_id, created.thread_id, "one")
        await app.add_comment(session.session_id, created.thread_id, "two")

        with pytest.raises(ThreadFullError):
            await app.add_comment(session.session_id, created.thread_id, "three")


async def test_reply_to_an_unknown_comment_is_rejected(
    comment_app: CommentApplication,
    authorization: FakeAuthorization,
) -> None:
    """A parent must belong to the thread and be live."""
    session = authorization.add_session()
    created = await comment_app.create_thread(session.session_id, "table", uuid4(), "root")

    with pytest.raises(UnknownCommentError):
        await comment_app.add_comment(
            session.session_id,
            created.thread_id,
            "reply",
            parent_comment_id=uuid4(),
        )


async def test_edit_requires_the_author_or_an_admin(
    comment_app: CommentApplication,
    authorization: FakeAuthorization,
) -> None:
    """Another user cannot edit, an administrator can."""
    author = authorization.add_session(tenant_id=TENANT)
    other = authorization.add_session(tenant_id=TENANT)
    admin = authorization.add_session(tenant_id=TENANT, is_system_admin=True)
    created = await comment_app.create_thread(author.session_id, "table", uuid4(), "root")

    with pytest.raises(CommentAuthorMismatchError):
        await comment_app.edit_comment(
            other.session_id,
            created.thread_id,
            created.root_comment_id,
            body="hijack",
        )

    await comment_app.edit_comment(
        admin.session_id,
        created.thread_id,
        created.root_comment_id,
        body="reviewed",
    )
    thread = await comment_app.repository.get(created.thread_id)
    assert thread.comments[created.root_comment_id].body == "reviewed"


async def test_resolve_requires_the_creator_or_a_target_permission(
    build_app: BuildApp,
    authorization: FakeAuthorization,
) -> None:
    """With tenant scoping on, a stranger needs the target permission."""
    creator = authorization.add_session(tenant_id=TENANT)
    stranger = authorization.add_session(tenant_id=TENANT)
    target = uuid4()

    async with build_app(CommentOptions(enforce_target_tenant=True)) as app:
        created = await app.create_thread(creator.session_id, "table", target, "root")

        with pytest.raises(PermissionDeniedError):
            await app.resolve_thread(stranger.session_id, created.thread_id)

        authorization.grant(stranger, "table", target, "resolve")
        await app.resolve_thread(stranger.session_id, created.thread_id)
        thread = await app.repository.get(created.thread_id)
        assert thread.status == "RESOLVED"
        assert thread.resolved_by == stranger.user_id


async def test_reads_require_a_session_by_default(
    build_app: BuildApp,
    authorization: FakeAuthorization,
    comment_view: SQLAlchemyCommentView,
) -> None:
    """The read guard is configurable."""
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
        "body",
        [],
        NOW,
        Tracking("comment_application", 1),
    )

    async with build_app() as app:
        with pytest.raises(AuthenticationError):
            await app.get_thread(thread_id)

    async with build_app(CommentOptions(read_requires_session=False)) as app:
        detail = await app.get_thread(thread_id)
        assert detail.thread.thread_id == thread_id
        assert [comment.body for comment in detail.comments] == ["body"]


async def test_reads_hide_a_thread_of_another_tenant(
    build_app: BuildApp,
    authorization: FakeAuthorization,
    comment_view: SQLAlchemyCommentView,
) -> None:
    """A thread of another tenant is reported as unknown."""
    owner = authorization.add_session(tenant_id=uuid4())
    reader = authorization.add_session(tenant_id=TENANT)
    thread_id = uuid4()
    await comment_view.register_thread(
        thread_id,
        "table",
        uuid4(),
        "",
        owner.user_id,
        owner.tenant_id,
        uuid4(),
        "body",
        [],
        NOW,
        Tracking("comment_application", 1),
    )

    async with build_app() as app:
        detail = await app.get_thread(thread_id, owner.session_id)
        assert detail.thread.thread_id == thread_id

        with pytest.raises(UnknownThreadError):
            await app.get_thread(thread_id, reader.session_id)


async def test_pagination_defaults_are_clamped(
    build_app: BuildApp,
    authorization: FakeAuthorization,
    comment_view: SQLAlchemyCommentView,
) -> None:
    """A page size above the maximum is clamped instead of rejected."""
    session = authorization.add_session(tenant_id=TENANT)
    for index in range(5):
        await comment_view.register_thread(
            uuid4(),
            "table",
            uuid4(),
            "",
            session.user_id,
            TENANT,
            uuid4(),
            "body",
            [],
            NOW,
            Tracking("comment_application", index + 1),
        )

    async with build_app(CommentOptions(default_page_size=1, max_page_size=2)) as app:
        assert len(await app.list_threads(session.session_id)) == 1
        assert len(await app.list_threads(session.session_id, limit=500)) == 2
