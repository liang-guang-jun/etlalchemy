"""Shared fixtures for the comment context tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from etlalchemy.comment.application import CommentApplication, CommentOptions
from etlalchemy.comment.projection.sqlalchemy import SQLAlchemyCommentView
from eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore

from tests.comment.support import FakeAuthorization, FakeTargetLookup


@pytest.fixture
def authorization() -> FakeAuthorization:
    """Returns an empty fake authorization port."""
    return FakeAuthorization()


@pytest.fixture
def target_lookup() -> FakeTargetLookup:
    """Returns an empty fake target lookup."""
    return FakeTargetLookup()


@pytest.fixture
async def comment_view(
    datastore: AsyncSQLAlchemyDatastore,
) -> AsyncIterator[SQLAlchemyCommentView]:
    """Returns an empty comment view whose tables exist."""
    view = SQLAlchemyCommentView(
        datastore=datastore,
        tracking_table=datastore.create_tracking_table("comment_projection_tracking"),
    )
    await view.create_table()
    yield view


@pytest.fixture
def build_app(
    authorization: FakeAuthorization,
    target_lookup: FakeTargetLookup,
    comment_view: SQLAlchemyCommentView,
    app_env: dict[str, str],
) -> object:
    """Returns a factory that starts a comment application with given options."""

    @asynccontextmanager
    async def build(
        options: CommentOptions | None = None,
    ) -> AsyncIterator[CommentApplication]:
        application = CommentApplication(
            view=comment_view,
            iam=authorization,
            target_lookup=target_lookup,
            options=options or CommentOptions(),
            env=app_env,
        )
        async with application:
            yield application

    return build


@pytest.fixture
async def comment_app(
    authorization: FakeAuthorization,
    target_lookup: FakeTargetLookup,
    comment_view: SQLAlchemyCommentView,
    app_env: dict[str, str],
) -> AsyncIterator[CommentApplication]:
    """Returns a started comment application with the default options."""
    application = CommentApplication(
        view=comment_view,
        iam=authorization,
        target_lookup=target_lookup,
        options=CommentOptions(),
        env=app_env,
    )
    async with application:
        yield application
