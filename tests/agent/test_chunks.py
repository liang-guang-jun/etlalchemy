"""Tests of the reasoning/content split of a streamed model chunk."""

from __future__ import annotations

from typing import Any

from etlalchemy.agent.runtime import _final_text, _split_delta
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage


def chunk(content: Any, **extra: Any) -> AIMessageChunk:
    """Builds a streamed chunk with the given content and extra kwargs."""
    return AIMessageChunk(content=content, additional_kwargs=dict(extra))


def test_a_plain_string_is_the_answer() -> None:
    """A provider that streams text alone produces no reasoning."""
    assert _split_delta(chunk("hello")) == ("", "hello")


def test_reasoning_blocks_are_not_the_answer() -> None:
    """Anthropic-style reasoning blocks are split from the text block."""
    reasoning, content = _split_delta(
        chunk(
            [
                {"type": "reasoning", "reasoning": "thinking"},
                {"type": "text", "text": "answer"},
            ]
        )
    )
    assert (reasoning, content) == ("thinking", "answer")


def test_reasoning_content_in_additional_kwargs_is_picked_up() -> None:
    """DeepSeek streams its thinking in ``additional_kwargs``."""
    assert _split_delta(chunk("", reasoning_content="hmm")) == ("hmm", "")


def test_a_block_list_wins_over_the_extra_field() -> None:
    """A provider that reports both is not counted twice."""
    reasoning, content = _split_delta(
        chunk(
            [{"type": "reasoning", "reasoning": "block"}],
            reasoning_content="extra",
        )
    )
    assert (reasoning, content) == ("block", "")


def test_an_unknown_block_shape_is_ignored() -> None:
    """A malformed block contributes no text instead of raising."""
    assert _split_delta(chunk([{"role": "user"}])) == ("", "")


def test_summary_reasoning_and_plain_string_answer_are_split() -> None:
    """The Databricks gateway mixes summary reasoning, strings and text blocks."""
    reasoning, content = _split_delta(
        chunk(
            [
                "",
                {
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": "think"}],
                },
                "answer",
            ]
        )
    )

    assert (reasoning, content) == ("think", "answer")


def test_a_plain_string_list_is_the_answer() -> None:
    """A list of strings concatenates into the answer."""
    assert _split_delta(chunk(["", "hello", " world"])) == ("", "hello world")


def test_final_text_reads_mixed_content_blocks() -> None:
    """The final state of a provider that answers in blocks keeps its text."""
    message = AIMessage(
        content=[
            "",
            {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "think"}],
            },
            "the answer",
        ]
    )
    messages = [HumanMessage(content="a question"), message]

    assert _final_text({"messages": messages}, turn="a question") == "the answer"


def test_final_text_skips_an_empty_last_message() -> None:
    """A trailing empty message does not hide an earlier answer of the turn."""
    messages = [
        HumanMessage(content="a question"),
        AIMessage(content="earlier answer"),
        AIMessage(content=""),
    ]

    assert _final_text({"messages": messages}, turn="a question") == "earlier answer"
