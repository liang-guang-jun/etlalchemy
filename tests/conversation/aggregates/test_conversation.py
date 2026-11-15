"""Tests of the Conversation aggregate."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from etlalchemy.conversation.aggregates.conversation import Conversation
from etlalchemy.conversation.aggregates.errors import (
    ApprovalAlreadyDecidedError,
    ConversationFullError,
    DiscardedError,
    DuplicateMessageError,
    DuplicateRunError,
    InvalidRunTransitionError,
    MessageEmptyError,
    MessageTooLongError,
    RunInProgressError,
    UnknownApprovalError,
    UnknownMessageError,
    UnknownRunError,
)
from etlalchemy.conversation.aggregates.types import (
    ResourceAccess,
    TokenUsage,
    ToolCallRecord,
)

USER = uuid4()
TENANT = uuid4()
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def make_conversation(**overrides: object) -> Conversation:
    """Builds an open conversation owned by :data:`USER`."""
    parameters: dict[str, object] = {
        "user_id": USER,
        "tenant_id": TENANT,
        "created_at": NOW,
        "title": "pricing",
    }
    parameters.update(overrides)
    return Conversation(**parameters)  # type: ignore[arg-type]


def append(conversation: Conversation, content: str = "hello") -> object:
    """Appends one user message and returns its id."""
    message_id = uuid4()
    conversation.append_user_message(message_id, content, NOW, 10, 100)
    return message_id


def test_append_user_message_records_it() -> None:
    """A user message is stored with its role and content."""
    conversation = make_conversation()
    message_id = append(conversation, "  hello  ")
    message = conversation.message_of(message_id)  # type: ignore[arg-type]
    assert message.role == "user"
    assert message.content == "hello"
    assert message.interrupted is False
    assert conversation.message_count == 1


def test_duplicate_message_id_is_rejected() -> None:
    """A message id may be used once."""
    conversation = make_conversation()
    message_id = uuid4()
    conversation.append_user_message(message_id, "hello", NOW, 10, 100)
    with pytest.raises(DuplicateMessageError):
        conversation.append_user_message(message_id, "again", NOW, 10, 100)


def test_editing_a_user_message_drops_its_successors() -> None:
    """The edited body wins and every later message and run disappears."""
    conversation = make_conversation()
    first = append(conversation, "first")
    second = append(conversation, "second")
    assistant = uuid4()
    conversation.complete_assistant_message(assistant, "answer", NOW, 10, 100)
    run_id = uuid4()
    conversation.start_run(run_id, assistant, NOW)
    conversation.finish_run(run_id, "completed", NOW)

    conversation.edit_user_message(first, "  edited  ", NOW, 100)  # type: ignore[arg-type]

    assert conversation.message_of(first).content == "edited"  # type: ignore[arg-type]
    with pytest.raises(UnknownMessageError):
        conversation.message_of(second)  # type: ignore[arg-type]
    with pytest.raises(UnknownMessageError):
        conversation.message_of(assistant)
    assert run_id not in conversation.runs
    assert conversation.message_count == 1


def test_editing_the_last_message_keeps_it() -> None:
    """A message without successors is only rewritten."""
    conversation = make_conversation()
    message_id = append(conversation, "old")

    conversation.edit_user_message(message_id, "new", NOW, 100)  # type: ignore[arg-type]

    assert conversation.message_of(message_id).content == "new"  # type: ignore[arg-type]
    assert conversation.message_count == 1


def test_editing_needs_a_user_message() -> None:
    """An unknown id or an assistant message is rejected."""
    conversation = make_conversation()
    assistant = uuid4()
    conversation.complete_assistant_message(assistant, "answer", NOW, 10, 100)

    with pytest.raises(UnknownMessageError):
        conversation.edit_user_message(uuid4(), "x", NOW, 100)
    with pytest.raises(UnknownMessageError):
        conversation.edit_user_message(assistant, "x", NOW, 100)


def test_editing_is_rejected_while_a_run_is_running() -> None:
    """An in-flight run owns the transcript until it ends."""
    conversation = make_conversation()
    message_id = append(conversation, "hello")
    conversation.start_run(uuid4(), uuid4(), NOW)

    with pytest.raises(RunInProgressError):
        conversation.edit_user_message(message_id, "new", NOW, 100)  # type: ignore[arg-type]


def test_editing_rejects_a_blank_body() -> None:
    """The new body follows the same validation as an appended one."""
    conversation = make_conversation()
    message_id = append(conversation, "hello")

    with pytest.raises(MessageEmptyError):
        conversation.edit_user_message(message_id, "   ", NOW, 100)  # type: ignore[arg-type]


def test_blank_and_long_bodies_are_rejected() -> None:
    """A blank body and an over-long body are domain errors."""
    conversation = make_conversation()
    with pytest.raises(MessageEmptyError):
        conversation.append_user_message(uuid4(), "   ", NOW, 10, 100)
    with pytest.raises(MessageTooLongError):
        conversation.append_user_message(uuid4(), "x" * 101, NOW, 10, 100)


def test_full_conversation_is_rejected() -> None:
    """The hard message cap stops further messages."""
    conversation = make_conversation()
    conversation.append_user_message(uuid4(), "one", NOW, 1, 100)
    with pytest.raises(ConversationFullError):
        conversation.append_user_message(uuid4(), "two", NOW, 1, 100)


def test_assistant_message_keeps_its_trace() -> None:
    """The assistant message stores resources, tools and token usage."""
    conversation = make_conversation()
    message_id = uuid4()
    conversation.complete_assistant_message(
        message_id,
        "answer",
        NOW,
        10,
        100,
        resources=(ResourceAccess(uri="catalog:///all", size_bytes=12),),
        tools=(ToolCallRecord(tool="list_models", status="ok", duration_ms=42),),
        token_usage=TokenUsage(input_tokens=3, output_tokens=5),
        interrupted=True,
    )
    message = conversation.message_of(message_id)
    assert message.role == "assistant"
    assert message.resources[0].uri == "catalog:///all"
    assert message.tools[0].tool == "list_models"
    assert message.token_usage.total_tokens == 8
    assert message.interrupted is True


def test_assistant_body_is_truncated() -> None:
    """An over-long assistant body is truncated instead of rejected."""
    conversation = make_conversation()
    message_id = uuid4()
    conversation.complete_assistant_message(message_id, "x" * 200, NOW, 10, 50)
    message = conversation.message_of(message_id)
    assert len(message.content) == 50
    assert message.content.endswith("…(truncated)")


def test_reasoning_is_recorded_after_the_message() -> None:
    """The thinking of an assistant message is kept and capped."""
    conversation = make_conversation()
    message_id = uuid4()
    conversation.complete_assistant_message(message_id, "answer", NOW, 10, 100)
    conversation.record_assistant_reasoning(message_id, "x" * 200, NOW, 20)
    message = conversation.message_of(message_id)
    assert len(message.reasoning) == 20
    assert message.reasoning.endswith("…(truncated)")
    assert message.content == "answer"


def test_reasoning_needs_an_assistant_message() -> None:
    """Thinking cannot be attached to an unknown or user message."""
    conversation = make_conversation()
    with pytest.raises(UnknownMessageError):
        conversation.record_assistant_reasoning(uuid4(), "thinking", NOW, 100)
    user_message_id = append(conversation)
    with pytest.raises(UnknownMessageError):
        conversation.record_assistant_reasoning(
            user_message_id,  # type: ignore[arg-type]
            "thinking",
            NOW,
            100,
        )


def test_run_lifecycle_with_an_approval() -> None:
    """A run is started, asks for an approval, is decided and finished."""
    conversation = make_conversation()
    run_id = uuid4()
    message_id = uuid4()
    approval_id = uuid4()
    conversation.start_run(run_id, message_id, NOW)
    assert conversation.run_of(run_id).status == "running"

    conversation.request_approval(
        approval_id,
        run_id,
        "discard_catalog",
        "hash",
        "destructive",
        NOW,
    )
    assert conversation.approval_of(run_id, approval_id).status == "pending"

    conversation.decide_approval(approval_id, run_id, True, USER, NOW)
    assert conversation.approval_of(run_id, approval_id).status == "approved"

    conversation.finish_run(run_id, "completed", NOW)
    run = conversation.run_of(run_id)
    assert run.status == "completed"
    assert run.finished_at == NOW


def test_run_rules() -> None:
    """Duplicate runs, double decisions and double finishes are rejected."""
    conversation = make_conversation()
    run_id = uuid4()
    conversation.start_run(run_id, uuid4(), NOW)
    with pytest.raises(DuplicateRunError):
        conversation.start_run(run_id, uuid4(), NOW)

    approval_id = uuid4()
    conversation.request_approval(approval_id, run_id, "discard_catalog", "h", "r", NOW)
    conversation.decide_approval(approval_id, run_id, False, USER, NOW)
    with pytest.raises(ApprovalAlreadyDecidedError):
        conversation.decide_approval(approval_id, run_id, True, USER, NOW)

    conversation.finish_run(run_id, "completed", NOW)
    with pytest.raises(InvalidRunTransitionError):
        conversation.finish_run(run_id, "failed", NOW)
    with pytest.raises(InvalidRunTransitionError):
        conversation.finish_run(run_id, "running", NOW)
    with pytest.raises(UnknownRunError):
        conversation.finish_run(uuid4(), "completed", NOW)


def test_unknown_references_are_rejected() -> None:
    """Unknown message, run and approval ids raise."""
    conversation = make_conversation()
    with pytest.raises(UnknownMessageError):
        conversation.message_of(uuid4())
    with pytest.raises(UnknownRunError):
        conversation.run_of(uuid4())
    run_id = uuid4()
    conversation.start_run(run_id, uuid4(), NOW)
    with pytest.raises(UnknownApprovalError):
        conversation.approval_of(run_id, uuid4())


def test_switch_provider_and_rename() -> None:
    """The conversation remembers its selected provider and title."""
    conversation = make_conversation()
    provider_id = uuid4()
    conversation.switch_provider(provider_id)
    assert conversation.active_llm_provider_id == provider_id
    conversation.rename("  renamed  ")
    assert conversation.title == "renamed"
    conversation.switch_provider(None)
    assert conversation.active_llm_provider_id is None


def test_discard_is_terminal() -> None:
    """A discarded conversation rejects every command."""
    conversation = make_conversation()
    conversation.discard(USER, NOW)
    assert conversation.is_discarded
    with pytest.raises(DiscardedError):
        conversation.rename("other")
    with pytest.raises(DiscardedError):
        conversation.append_user_message(uuid4(), "hello", NOW, 10, 100)
    with pytest.raises(DiscardedError):
        conversation.discard(USER, NOW)
