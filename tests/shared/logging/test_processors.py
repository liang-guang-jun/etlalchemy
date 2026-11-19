"""Tests for the stdout rendering processor."""

from __future__ import annotations

import re
from typing import Any

import pytest
from etlalchemy.shared.logging.processors import render_stdout_line, stdout_renderer

ANSI = re.compile(r"\033\[[0-9;]*m")
"""Matches the ANSI escape sequences the colour mode emits."""


def render(**fields: Any) -> str:
    """Renders one event dictionary without colours."""
    return render_stdout_line(False, None, "info", dict(fields))


def test_line_has_the_documented_shape() -> None:
    """The line is ``[asctime][name][level] message k=v``."""
    line = render(
        timestamp="2025-01-12 10:31:07",
        level="info",
        logger="catalog.application",
        event="catalog.create done",
        catalog_id="3f1c",
    )

    assert line == "[2025-01-12 10:31:07][INFO][catalog.application] catalog.create done catalog_id=3f1c"


def test_line_has_no_trailing_space_without_extra_fields() -> None:
    """A message without fields does not end in whitespace."""
    line = render(timestamp="2025-01-12 10:31:07", level="info", logger="x", event="hello")

    assert line == "[2025-01-12 10:31:07][INFO][x] hello"


def test_timestamp_defaults_to_now() -> None:
    """A missing timestamp falls back to the current local time."""
    line = render(level="info", logger="x", event="hello")

    assert re.match(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]", line)


def test_level_falls_back_to_the_method_name() -> None:
    """Without ``add_log_level`` the logging method names the level."""
    line = render_stdout_line(False, None, "warning", {"event": "hello"})

    assert "][WARNING][" in line


def test_values_with_spaces_are_json_quoted() -> None:
    """Quoting keeps a value with spaces inside one ``k=v`` pair."""
    line = render(event="hello", note="two words")

    assert line.endswith('note="two words"')


def test_newlines_in_values_do_not_break_the_line() -> None:
    """Tracebacks and multi-line strings stay on a single line."""
    line = render(event="failed", exception="Traceback:\n  boom")

    assert "\n" not in line
    assert "exception=" in line


@pytest.mark.parametrize(
    ("value", "rendered"),
    [(None, "None"), (True, "True"), (3, "3"), (1.5, "1.5"), (["a", "b"], '["a", "b"]')],
)
def test_scalars_and_containers_are_rendered(value: object, rendered: str) -> None:
    """Scalars keep their Python spelling; containers become JSON."""
    line = render(event="hello", value=value)

    assert line.endswith(f"value={rendered}")


def test_colours_wrap_the_level_and_the_logger_name() -> None:
    """Coloured output is the plain line plus ANSI escapes."""
    fields = {
        "timestamp": "2025-01-12 10:31:07",
        "level": "error",
        "logger": "catalog.application",
        "event": "boom",
    }
    plain = render_stdout_line(False, None, "error", dict(fields))
    coloured = render_stdout_line(True, None, "error", dict(fields))

    assert ANSI.sub("", coloured) == plain
    assert "\033[31m" in coloured
    assert coloured.startswith("[2025-01-12 10:31:07][\033[31m")


def test_renderer_closes_over_the_colour_choice() -> None:
    """``stdout_renderer`` returns a processor with the given colour setting."""
    processor = stdout_renderer(colors=False)

    line = processor(None, "info", {"timestamp": "t", "level": "info", "logger": "x", "event": "hi"})

    assert line == "[t][INFO][x] hi"
    assert "\033[" not in line
