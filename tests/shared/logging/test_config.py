"""Tests for the process-wide logging configuration."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
import structlog
from etlalchemy.shared.logging import configure_logging, get_logger, reset_logging
from structlog.stdlib import ProcessorFormatter
from structlog.testing import capture_logs


def settings(**overrides: Any) -> SimpleNamespace:
    """Returns logging settings with the documented defaults."""
    values: dict[str, Any] = {
        "level": "INFO",
        "mode": "stdout",
        "color": False,
        "quiet": [],
        "loggers": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def record_configure(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Records the keyword arguments passed to ``structlog.configure``."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(structlog, "configure", lambda **kwargs: calls.append(kwargs))
    return calls


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    """Starts and ends every test from the state the process had before."""
    reset_logging()
    yield
    reset_logging()


def test_configure_logging_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the first call configures structlog."""
    calls = record_configure(monkeypatch)

    configure_logging(settings())
    configure_logging(settings())

    assert len(calls) == 1
    assert calls[0]["cache_logger_on_first_use"] is True


def test_structlog_chain_wraps_for_the_shared_formatter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No renderer stays in the structlog chain; the formatter renders both paths."""
    calls = record_configure(monkeypatch)

    configure_logging(settings())

    assert calls[0]["processors"][0] is structlog.contextvars.merge_contextvars
    assert calls[0]["processors"][-1] is ProcessorFormatter.wrap_for_formatter


def test_stdout_mode_renders_the_documented_line(capsys: pytest.CaptureFixture[str]) -> None:
    """A structlog event prints the ``[asctime][name][level] msg k=v`` line."""
    configure_logging(settings(mode="stdout", color=False))

    get_logger("demo").info("hello", answer=42)

    line = capsys.readouterr().out.strip()
    assert line.startswith("[")
    assert "][INFO][demo] hello answer=42" in line


def test_json_mode_renders_one_object_per_line(capsys: pytest.CaptureFixture[str]) -> None:
    """``mode=json`` prints a single JSON object with the standard fields."""
    configure_logging(settings(mode="json"))

    get_logger("demo").info("hello", answer=42)

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["event"] == "hello"
    assert payload["level"] == "info"
    assert payload["logger"] == "demo"
    assert payload["answer"] == 42
    assert "timestamp" in payload


def test_stdlib_record_uses_the_same_format(capsys: pytest.CaptureFixture[str]) -> None:
    """A foreign stdlib record goes through the same renderer."""
    configure_logging(settings(mode="stdout", color=False))

    logging.getLogger("uvicorn.error").info("Started server process [1]")

    line = capsys.readouterr().out.strip()
    assert line.startswith("[")
    assert "][INFO][uvicorn.error] Started server process [1]" in line


def test_stdlib_json_record_keeps_the_ascii_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A foreign record's exception is rendered as one JSON field."""
    configure_logging(settings(mode="json"))

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logging.getLogger("httpcore").exception("failed")

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["event"] == "failed"
    assert "RuntimeError: boom" in payload["exception"]


def test_uvicorn_handlers_are_detached() -> None:
    """A pre-configured uvicorn logger propagates to the root handler again."""
    logger = logging.getLogger("uvicorn.access")
    logger.addHandler(logging.NullHandler())
    logger.propagate = False

    configure_logging(settings())

    assert logger.handlers == []
    assert logger.propagate is True


def test_quiet_silences_a_logger(capsys: pytest.CaptureFixture[str]) -> None:
    """A quiet logger emits nothing."""
    configure_logging(settings(quiet=["noisy.lib"]))

    logging.getLogger("noisy.lib").warning("should not appear")

    assert capsys.readouterr().out == ""


def test_quiet_silences_child_loggers(capsys: pytest.CaptureFixture[str]) -> None:
    """A child logger inherits the quiet level of its parent."""
    configure_logging(settings(quiet=["httpx"]))

    logging.getLogger("httpx._client").warning("nope")

    assert capsys.readouterr().out == ""


def test_loggers_override_quiet_for_the_same_name(capsys: pytest.CaptureFixture[str]) -> None:
    """``loggers`` is applied after ``quiet``, so it wins for the same logger."""
    configure_logging(settings(quiet=["uvicorn.access"], loggers={"uvicorn.access": "WARNING"}))

    logging.getLogger("uvicorn.access").warning("kept")

    assert "kept" in capsys.readouterr().out


def test_level_filters_lower_events() -> None:
    """Events below the configured level never reach the processors."""
    configure_logging(settings(level="INFO"))

    with capture_logs() as logs:
        logger = get_logger("probe")
        logger.debug("dropped")
        logger.info("kept")

    assert [entry["event"] for entry in logs] == ["kept"]


def test_reset_logging_restores_the_handlers() -> None:
    """The root handlers and level come back unchanged."""
    root = logging.getLogger()
    handlers = list(root.handlers)
    level = root.level

    configure_logging(settings())
    reset_logging()

    assert root.handlers == handlers
    assert root.level == level


def test_reset_logging_restores_logger_levels() -> None:
    """A silenced logger returns to its previous level."""
    logger = logging.getLogger("noisy.lib")
    previous = logger.level

    configure_logging(settings(quiet=["noisy.lib"]))
    assert logger.level == logging.CRITICAL + 1

    reset_logging()
    assert logger.level == previous


def test_reset_logging_allows_reconfiguration(monkeypatch: pytest.MonkeyPatch) -> None:
    """``reset_logging`` clears the idempotency flag and the logger cache."""
    calls = record_configure(monkeypatch)

    configure_logging(settings())
    reset_logging()
    configure_logging(settings())

    assert len(calls) == 2


def test_get_logger_caches_per_name() -> None:
    """The same name returns the same logger object, another name a different one."""
    assert get_logger("catalog.application") is get_logger("catalog.application")
    assert get_logger("catalog.application") is not get_logger("ingestion.application")


def test_reset_logging_clears_the_logger_cache() -> None:
    """A logger created before the reset is rebuilt afterwards."""
    first = get_logger("catalog.application")

    reset_logging()

    assert get_logger("catalog.application") is not first
