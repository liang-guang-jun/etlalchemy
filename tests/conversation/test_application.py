"""Tests of the conversation application service."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from etlalchemy.conversation.aggregates.errors import (
    RunInProgressError,
    UnknownConversationError,
)
from etlalchemy.conversation.aggregates.types import (
    ResourceAccess,
    TokenUsage,
    ToolCallRecord,
)
from etlalchemy.iam.aggregates.errors import PermissionDeniedError
from etlalchemy.conversation.application import ConversationOptions
from tests.conversation.support import FakeAuthorization, running_conversation

TENANT = uuid4()


async def test_messages_runs_and_approvals_round_trip(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
) -> None:
    """A whole run materialises with its trace, status and decision."""
    async with running_conversation(app_env, authorization) as (app, _, sync):
        session = authorization.add_session(tenant_id=TENANT)
        conversation_id = await app.start_conversation(session.session_id, "pricing")

        question = await app.append_user_message(
            session.session_id,
            conversation_id,
            "list the models",
        )
        run = await app.start_run(
            session.session_id,
            conversation_id,
            question.message_id,
        )
        approval_id = await app.request_approval(
            session.session_id,
            conversation_id,
            run.run_id,
            "discard_catalog",
            "hash",
            "destructive tool",
        )
        await app.decide_approval(
            session.session_id,
            conversation_id,
            run.run_id,
            approval_id,
            True,
        )
        answer = await app.complete_assistant_message(
            session.session_id,
            conversation_id,
            "here they are",
            resources=(ResourceAccess(uri="catalog:///all", size_bytes=1280),),
            tools=(
                ToolCallRecord(
                    tool="list_models",
                    status="ok",
                    duration_ms=42,
                    args_json='{"catalog": "crm"}',
                    result_preview="[]",
                ),
            ),
            token_usage=TokenUsage(input_tokens=10, output_tokens=20),
            reasoning="the user wants the models of crm",
        )
        await app.finish_run(session.session_id, conversation_id, run.run_id, "completed")
        await sync()

        messages = await app.list_messages(session.session_id, conversation_id)
        assert [row.message_id for row in messages] == [
            question.message_id,
            answer.message_id,
        ]
        assert messages[0].role == "user"
        assistant = messages[1]
        assert assistant.role == "assistant"
        assert assistant.content == "here they are"
        assert assistant.resources[0].uri == "catalog:///all"
        assert assistant.tools[0].tool == "list_models"
        assert assistant.tools[0].args_json == '{"catalog": "crm"}'
        assert assistant.tools[0].result_preview == "[]"
        assert assistant.reasoning == "the user wants the models of crm"
        assert assistant.input_tokens == 10
        assert assistant.output_tokens == 20
        assert assistant.interrupted is False

        conversation = await app.get_conversation(session.session_id, conversation_id)
        assert conversation.title == "pricing"
        assert conversation.message_count == 2
        assert conversation.run_count == 1
        assert conversation.user_id == session.user_id
        assert conversation.tenant_id == TENANT

        stored_run = await app.get_run(session.session_id, run.run_id)
        assert stored_run.status == "completed"
        assert [row.status for row in stored_run.approvals] == ["approved"]
        assert stored_run.approvals[0].decided_by == session.user_id


async def test_interrupted_message_is_kept(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
) -> None:
    """An interrupted stream still leaves a truthful assistant message."""
    async with running_conversation(app_env, authorization) as (app, _, sync):
        session = authorization.add_session()
        conversation_id = await app.start_conversation(session.session_id)
        await app.complete_assistant_message(
            session.session_id,
            conversation_id,
            "partial answer",
            interrupted=True,
        )
        await sync()
        messages = await app.list_messages(session.session_id, conversation_id)
        assert messages[0].interrupted is True


async def test_editing_a_message_truncates_and_returns_history(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
) -> None:
    """Editing keeps the prefix, rewrites the body and drops the rest."""
    async with running_conversation(app_env, authorization) as (app, _, sync):
        session = authorization.add_session()
        conversation_id = await app.start_conversation(session.session_id)
        first = await app.append_user_message(session.session_id, conversation_id, "first")
        answer = await app.complete_assistant_message(session.session_id, conversation_id, "answer")
        second = await app.append_user_message(session.session_id, conversation_id, "second")
        await app.complete_assistant_message(session.session_id, conversation_id, "second answer")
        await sync()

        history = await app.edit_user_message(
            session.session_id,
            conversation_id,
            second.message_id,
            "edited second",
        )
        await sync()

        assert history == (("user", "first"), ("assistant", "answer"))
        rows = await app.list_messages(session.session_id, conversation_id)
        assert [(row.message_id, row.content) for row in rows] == [
            (first.message_id, "first"),
            (answer.message_id, "answer"),
            (second.message_id, "edited second"),
        ]


async def test_pending_approvals_are_listed_until_decided(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
) -> None:
    """A paused run offers its cards again after a reload, until it is decided."""
    async with running_conversation(app_env, authorization) as (app, _, sync):
        session = authorization.add_session()
        conversation_id = await app.start_conversation(session.session_id)
        question = await app.append_user_message(session.session_id, conversation_id, "go")
        run = await app.start_run(
            session.session_id,
            conversation_id,
            question.message_id,
        )
        approval_id = await app.request_approval(
            session.session_id,
            conversation_id,
            run.run_id,
            "approve_term",
            "hash",
            "no hint",
        )
        await sync()

        pending = await app.list_pending_approvals(session.session_id, conversation_id)
        assert [row.approval_id for row in pending] == [approval_id]
        assert pending[0].run_id == run.run_id
        assert pending[0].tool == "approve_term"

        await app.decide_approval(
            session.session_id,
            conversation_id,
            run.run_id,
            approval_id,
            True,
        )
        await sync()

        assert await app.list_pending_approvals(session.session_id, conversation_id) == []


async def test_a_finished_run_does_not_offer_its_orphan_approval(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
) -> None:
    """A pending row left on a finished run is not offered as a decision."""
    async with running_conversation(app_env, authorization) as (app, _, sync):
        session = authorization.add_session()
        conversation_id = await app.start_conversation(session.session_id)
        question = await app.append_user_message(session.session_id, conversation_id, "go")
        run = await app.start_run(
            session.session_id,
            conversation_id,
            question.message_id,
        )
        await app.request_approval(
            session.session_id,
            conversation_id,
            run.run_id,
            "approve_term",
            "hash",
            "no hint",
        )
        await app.finish_run(session.session_id, conversation_id, run.run_id, "completed")
        await sync()

        assert await app.list_pending_approvals(session.session_id, conversation_id) == []


async def test_a_stale_pause_keeps_its_card_and_stops_blocking(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
) -> None:
    """A human can still answer a stale pause, but it no longer holds the chat."""
    options = ConversationOptions(run_stale_after_seconds=1)
    async with running_conversation(app_env, authorization, options=options) as (
        app,
        _,
        sync,
    ):
        session = authorization.add_session()
        conversation_id = await app.start_conversation(session.session_id)
        question = await app.append_user_message(session.session_id, conversation_id, "go")
        run = await app.start_run(
            session.session_id,
            conversation_id,
            question.message_id,
        )
        await app.request_approval(
            session.session_id,
            conversation_id,
            run.run_id,
            "approve_term",
            "hash",
            "no hint",
        )
        await sync()

        await asyncio.sleep(1.2)

        # The decision is still the way back into that run, so the card stays.
        assert await app.list_pending_approvals(session.session_id, conversation_id) != []
        # Nothing can continue it on its own, but the conversation is free again.
        second = await app.append_user_message(session.session_id, conversation_id, "next")
        assert second.conversation_id == conversation_id
        await sync()

        runs = await app.list_runs(session.session_id, conversation_id)
        assert [row.status for row in runs] == ["running"]


async def test_a_stale_run_without_a_decision_is_abandoned(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
) -> None:
    """A run nothing can continue is closed instead of blocking the conversation."""
    options = ConversationOptions(run_stale_after_seconds=1)
    async with running_conversation(app_env, authorization, options=options) as (
        app,
        _,
        sync,
    ):
        session = authorization.add_session()
        conversation_id = await app.start_conversation(session.session_id)
        question = await app.append_user_message(session.session_id, conversation_id, "go")
        await app.start_run(session.session_id, conversation_id, question.message_id)
        await sync()

        await asyncio.sleep(1.2)

        await app.append_user_message(session.session_id, conversation_id, "next")
        await sync()

        runs = await app.list_runs(session.session_id, conversation_id)
        assert runs[0].status == "interrupted"
        assert runs[0].error == "the run was abandoned after the stale window"


async def test_finishing_a_run_twice_keeps_the_first_status(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
) -> None:
    """The finalisation is idempotent, so a retry cannot overwrite the outcome."""
    async with running_conversation(app_env, authorization) as (app, _, sync):
        session = authorization.add_session()
        conversation_id = await app.start_conversation(session.session_id)
        question = await app.append_user_message(session.session_id, conversation_id, "go")
        run = await app.start_run(session.session_id, conversation_id, question.message_id)
        await sync()

        await app.finish_run(session.session_id, conversation_id, run.run_id, "completed")
        await app.finish_run(session.session_id, conversation_id, run.run_id, "failed", "too late")
        await sync()

        runs = await app.list_runs(session.session_id, conversation_id)
        assert runs[0].status == "completed"
        assert runs[0].error is None


async def test_pagination_is_bounded(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
) -> None:
    """Messages are returned page by page in creation order."""
    async with running_conversation(app_env, authorization) as (app, _, sync):
        session = authorization.add_session()
        conversation_id = await app.start_conversation(session.session_id)
        for index in range(5):
            await app.append_user_message(
                session.session_id,
                conversation_id,
                f"message {index}",
            )
        await sync()
        first = await app.list_messages(session.session_id, conversation_id, limit=2)
        rest = await app.list_messages(session.session_id, conversation_id, limit=2, offset=2)
        assert [row.content for row in first] == ["message 0", "message 1"]
        assert [row.content for row in rest] == ["message 2", "message 3"]


async def test_non_owner_is_denied(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
) -> None:
    """Another user neither reads nor changes the conversation."""
    async with running_conversation(app_env, authorization) as (app, _, sync):
        owner = authorization.add_session()
        other = authorization.add_session(tenant_id=owner.tenant_id)
        conversation_id = await app.start_conversation(owner.session_id)
        await sync()

        with pytest.raises(UnknownConversationError):
            await app.get_conversation(other.session_id, conversation_id)
        with pytest.raises(PermissionDeniedError):
            await app.append_user_message(
                other.session_id,
                conversation_id,
                "intruder",
            )

        admin = authorization.add_session(is_system_admin=True)
        row = await app.get_conversation(admin.session_id, conversation_id)
        assert row.conversation_id == conversation_id


async def test_discard_cascades(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
) -> None:
    """A discarded conversation disappears with its messages and runs."""
    async with running_conversation(app_env, authorization) as (app, _, sync):
        session = authorization.add_session()
        conversation_id = await app.start_conversation(session.session_id)
        message = await app.append_user_message(session.session_id, conversation_id, "hello")
        run = await app.start_run(session.session_id, conversation_id, message.message_id)
        await sync()

        await app.discard_conversation(session.session_id, conversation_id)
        await sync()

        assert await app.list_conversations(session.session_id) == []
        with pytest.raises(UnknownConversationError):
            await app.get_conversation(session.session_id, conversation_id)
        with pytest.raises(UnknownConversationError):
            await app.get_run(session.session_id, run.run_id)


async def test_switch_provider_persists(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
) -> None:
    """The conversation remembers the provider selected for it."""
    async with running_conversation(app_env, authorization) as (app, _, sync):
        session = authorization.add_session()
        provider_id = uuid4()
        conversation_id = await app.start_conversation(session.session_id)
        await app.switch_llm_provider(session.session_id, conversation_id, provider_id)
        await sync()
        row = await app.get_conversation(session.session_id, conversation_id)
        assert row.active_llm_provider_id == provider_id


async def test_a_message_while_a_run_is_running_is_rejected(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
) -> None:
    """Steering is unsupported: a second message waits for the run to finish."""
    async with running_conversation(app_env, authorization) as (app, _, sync):
        session = authorization.add_session()
        conversation_id = await app.start_conversation(session.session_id)
        first = await app.append_user_message(session.session_id, conversation_id, "hello")
        await app.start_run(session.session_id, conversation_id, first.message_id)
        await sync()

        with pytest.raises(RunInProgressError):
            await app.append_user_message(session.session_id, conversation_id, "steer")


async def test_a_zero_stale_window_disables_the_guard(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
) -> None:
    """A deployment may opt out of the one-run-per-conversation rule."""
    options = ConversationOptions(run_stale_after_seconds=0)
    async with running_conversation(app_env, authorization, options=options) as (
        app,
        _,
        sync,
    ):
        session = authorization.add_session()
        conversation_id = await app.start_conversation(session.session_id)
        first = await app.append_user_message(session.session_id, conversation_id, "hello")
        await app.start_run(session.session_id, conversation_id, first.message_id)
        await sync()

        second = await app.append_user_message(session.session_id, conversation_id, "steer")
        assert second.conversation_id == conversation_id
