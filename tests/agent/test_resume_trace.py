"""Tests of the trace a resumed run rebuilds."""

from __future__ import annotations

from etlalchemy.agent.mcp.tools import args_hash
from etlalchemy.agent.runtime import _restore_calls
from etlalchemy.agent.settings import AgentRuntimeSettings
from langchain_core.messages import AIMessage, ToolMessage

SETTINGS = AgentRuntimeSettings()


def test_pre_approval_calls_are_restored() -> None:
    """A resumed run keeps the call it paused on in its trace."""
    values = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "discard_catalog",
                        "args": {"catalog_id": "abc"},
                        "id": "call-1",
                        "type": "tool_call",
                    },
                ],
            ),
            ToolMessage(content="[denied]", tool_call_id="call-1", status="error"),
        ],
    }

    restored = _restore_calls(values, SETTINGS)

    assert [call.tool for call in restored] == ["discard_catalog"]
    assert restored[0].args_hash == args_hash({"catalog_id": "abc"})
    assert restored[0].status == "error"
    assert restored[0].args_json == '{"catalog_id": "abc"}'
    assert restored[0].result_preview == "[denied]"


def test_no_messages_restore_nothing() -> None:
    """An empty state yields an empty trace."""
    assert _restore_calls(None, SETTINGS) == []
    assert _restore_calls({"messages": []}, SETTINGS) == []


def test_a_call_without_a_result_is_marked_ok() -> None:
    """A call that never produced a tool message is not an error."""
    values = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "list_models", "args": {}, "id": "c2", "type": "tool_call"}],
            ),
        ],
    }

    restored = _restore_calls(values, SETTINGS)

    assert restored[0].status == "ok"
    assert restored[0].args_hash == args_hash({})
    assert restored[0].result_preview == ""
