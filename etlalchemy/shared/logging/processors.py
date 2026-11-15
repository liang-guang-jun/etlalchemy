"""structlog processor that renders the human-readable stdout line.

The line is ``[asctime][level][name] message k1=v1 k2=v2``; it must stay on one
line, so values containing spaces, newlines or nested structures are JSON encoded.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from typing import Any

from structlog.typing import EventDict

_LEVEL_COLORS = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[1;31m",
}
"""ANSI colour prefixes per level; unknown levels stay uncoloured."""

_RESET = "\033[0m"
_DIM = "\033[2m"
_QUOTED_ESCAPES = ('"', "\\", "\n", "\r", "\t")


def _format_value(value: Any) -> str:
    """Renders a field value so the ``k=v`` pairs stay parseable."""
    if isinstance(value, str):
        if any(character in value for character in _QUOTED_ESCAPES) or " " in value:
            return json.dumps(value, ensure_ascii=False)
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return str(value)
    return json.dumps(value, ensure_ascii=False, default=str)


def _timestamp(event_dict: EventDict) -> str:
    """Returns the timestamp field, or the current local time when absent."""
    value = event_dict.pop("timestamp", None)
    if value is None:
        return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def render_stdout_line(colors: bool, logger: Any, method_name: str, event_dict: EventDict) -> str:
    """Renders one event dictionary as a ``[asctime][level][name] message`` line.

    Args:
        colors: Whether to colour the level and the logger name.
        logger: The logger structlog passes to every processor.
        method_name: Logging method used, e.g. ``info``.
        event_dict: The event dictionary assembled by the earlier processors.

    Returns:
        A single-line string; the remaining fields are appended as ``k=v``.
    """
    del logger
    timestamp = _timestamp(event_dict)
    level = str(event_dict.pop("level", method_name)).upper()
    name = str(event_dict.pop("logger", ""))
    message = str(event_dict.pop("event", ""))
    pairs = " ".join(f"{key}={_format_value(value)}" for key, value in event_dict.items())
    if colors:
        level = f"{_LEVEL_COLORS.get(level, '')}{level}{_RESET}"
        name = f"{_DIM}{name}{_RESET}"
    line = f"[{timestamp}][{level}][{name}] {message}"
    return f"{line} {pairs}".rstrip()


def stdout_renderer(colors: bool) -> Callable[[Any, str, EventDict], str]:
    """Returns the terminal processor that formats the stdout line.

    Args:
        colors: Whether the rendered line uses ANSI colours.

    Returns:
        A processor to place at the end of the structlog chain.
    """

    def render(logger: Any, method_name: str, event_dict: EventDict) -> str:
        """Renders one event dictionary."""
        return render_stdout_line(colors, logger, method_name, event_dict)

    return render
