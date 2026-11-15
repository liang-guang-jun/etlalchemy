"""Cached access to structlog loggers.

Lives in its own module so :mod:`etlalchemy.shared.logging.config` and
:mod:`etlalchemy.shared.logging.context` never import each other.
"""

from __future__ import annotations

from functools import cache
from typing import cast

import structlog


@cache
def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Returns the structured logger registered under ``name``.

    Args:
        name: Logger name, conventionally ``<context>.<module>``.

    Returns:
        A cached bound logger; the cache must be cleared (see
        :func:`etlalchemy.shared.logging.config.reset_logging`) after
        reconfiguring structlog in tests.
    """
    return cast("structlog.stdlib.BoundLogger", structlog.get_logger(name))
