"""Shared fixtures for the conversation context tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from etlalchemy.conversation.application import ConversationApplication
from etlalchemy.conversation.projection.sqlalchemy import SQLAlchemyConversationView
from eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore

from tests.conversation.support import FakeAuthorization


@pytest.fixture
def authorization() -> FakeAuthorization:
    """Returns an empty fake authorization port."""
    return FakeAuthorization()


@pytest.fixture
async def conversation_view(
    datastore: AsyncSQLAlchemyDatastore,
) -> AsyncIterator[SQLAlchemyConversationView]:
    """Returns an empty conversation view whose tables exist."""
    view = SQLAlchemyConversationView(
        datastore=datastore,
        tracking_table=datastore.create_tracking_table("conversation_projection_tracking"),
    )
    await view.create_table()
    yield view


@pytest.fixture
async def conversation_app(
    authorization: FakeAuthorization,
    conversation_view: SQLAlchemyConversationView,
    app_env: dict[str, str],
) -> AsyncIterator[ConversationApplication]:
    """Returns a started conversation application on a temporary event store."""
    application = ConversationApplication(
        view=conversation_view,
        iam=authorization,
        env=app_env,
    )
    async with application:
        yield application
