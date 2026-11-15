"""contextvars helpers so bound values reach every log record."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import structlog


def bind_context(**kwargs: Any) -> None:
    """Binds key/values to the structlog contextvars of the current context."""
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Removes every contextvar value bound in the current context."""
    structlog.contextvars.clear_contextvars()


def get_context() -> dict[str, Any]:
    """Returns the contextvars currently bound.

    Returns:
        A copy of the bound key/values, empty when nothing is bound.
    """
    return structlog.contextvars.get_contextvars()


@contextmanager
def bound_context(**kwargs: Any) -> Iterator[None]:
    """Binds ``kwargs`` for the duration of the ``with`` block.

    Args:
        **kwargs: Values to bind, for example a ``request_id`` or ``run_id``.

    Yields:
        Nothing; the values are bound while the block runs.
    """
    structlog.contextvars.bind_contextvars(**kwargs)
    try:
        yield
    finally:
        structlog.contextvars.unbind_contextvars(*kwargs)
