"""Tests of the argument redaction and of the previews sent to the browser."""

from __future__ import annotations

from etlalchemy.agent.redaction import (
    DEFAULT_REDACT_KEYS,
    REDACTED,
    preview_json,
    preview_text,
    redact_arguments,
)

KEYS = frozenset(DEFAULT_REDACT_KEYS)


def test_a_sensitive_value_is_masked() -> None:
    """A top-level password never reaches the preview."""
    assert redact_arguments({"user": "u", "password": "hunter2"}, KEYS) == {
        "user": "u",
        "password": REDACTED,
    }


def test_matching_ignores_case_and_separators() -> None:
    """``apiKey`` and ``API-KEY`` both match ``api_key``."""
    redacted = redact_arguments({"apiKey": "1", "API-KEY": "2", "token": "3"}, KEYS)
    assert set(redacted.values()) == {REDACTED}


def test_nested_values_are_redacted_without_mutating_the_input() -> None:
    """Mappings inside mappings and lists are masked, the input is untouched."""
    arguments = {"options": {"secret": "s", "list": [{"token": "t"}]}}
    redacted = redact_arguments(arguments, KEYS)
    assert redacted == {"options": {"secret": REDACTED, "list": [{"token": REDACTED}]}}
    assert arguments["options"]["secret"] == "s"


def test_a_compound_name_is_matched_on_its_last_segment() -> None:
    """``options.token`` is recognised as a token."""
    assert redact_arguments({"options_token": "x"}, KEYS) == {"options_token": REDACTED}
    assert redact_arguments({"tokenizer": "x"}, KEYS) == {"tokenizer": "x"}


def test_preview_json_sorts_and_truncates() -> None:
    """The preview is deterministic JSON and honours the limit."""
    assert preview_json({"b": 2, "a": 1}, 0) == '{"a": 1, "b": 2}'
    cut = preview_json({"a": "x" * 100}, 20)
    assert len(cut) == 20
    assert cut.endswith("…(truncated)")


def test_preview_text_keeps_a_short_text() -> None:
    """A text below the limit is returned unchanged."""
    assert preview_text("ok", 10) == "ok"
    assert preview_text("ok", 0) == "ok"
