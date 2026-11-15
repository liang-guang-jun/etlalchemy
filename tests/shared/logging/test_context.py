"""Tests for the contextvars helpers."""

from __future__ import annotations

from etlalchemy.shared.logging import bind_context, bound_context, clear_context, get_context


def test_bind_context_adds_values() -> None:
    """``bind_context`` adds key/values to the current context."""
    clear_context()
    bind_context(request_id="abc", method="GET")

    assert get_context() == {"request_id": "abc", "method": "GET"}
    clear_context()


def test_clear_context_removes_every_value() -> None:
    """``clear_context`` empties the context."""
    bind_context(request_id="abc")

    clear_context()

    assert get_context() == {}


def test_bound_context_unbinds_on_exit() -> None:
    """Values bound by ``bound_context`` disappear after the block."""
    clear_context()

    with bound_context(run_id="run-1"):
        assert get_context() == {"run_id": "run-1"}

    assert get_context() == {}


def test_bound_context_unbinds_on_error() -> None:
    """The values are unbound even when the block raises."""
    clear_context()

    try:
        with bound_context(run_id="run-1"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert get_context() == {}


def test_nested_bound_contexts_stack() -> None:
    """An inner block adds to the outer one and removes only its own keys."""
    clear_context()

    with bound_context(run_id="outer"):
        with bound_context(connection_id="conn-1"):
            assert get_context() == {"run_id": "outer", "connection_id": "conn-1"}
        assert get_context() == {"run_id": "outer"}

    assert get_context() == {}
