"""Process-wide structlog configuration.

The shared layer must not depend on the assembly layer, so the settings arrive as
any object satisfying :class:`LoggingConfig` (the assembly layer's pydantic
``LoggingSettings`` does).

Two paths feed one renderer. structlog loggers end their chain with
``ProcessorFormatter.wrap_for_formatter`` and hand a record to the root handler,
while foreign stdlib records (uvicorn, httpx, ...) reach the same handler and are
prepared by ``foreign_pre_chain``. Both are rendered by the formatter's
``processor``, so the terminal never shows two different formats.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, TextIO

import structlog
from structlog.stdlib import ProcessorFormatter

from etlalchemy.shared.logging.logger import get_logger
from etlalchemy.shared.logging.processors import stdout_renderer

_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi")
"""Loggers uvicorn may have equipped with its own handler before we took over."""

_QUIET_LEVEL = logging.CRITICAL + 1
"""Level above ``CRITICAL``: such loggers never create a record."""

_CONFIGURED = False
"""Set once :func:`configure_logging` has run, so repeated calls are no-ops."""

_SAVED_ROOT: tuple[list[logging.Handler], int] | None = None
"""Root handlers and level replaced by :func:`configure_logging`."""

_SAVED_LOGGERS: dict[str, tuple[list[logging.Handler], bool, int]] = {}
"""Handlers, ``propagate`` flag and level of every third-party logger we touched."""


class LoggingConfig(Protocol):
    """The logging settings :func:`configure_logging` consumes."""

    @property
    def level(self) -> str:
        """Minimum level of the root logger."""
        ...

    @property
    def mode(self) -> str:
        """Rendering mode: ``json`` or ``stdout``."""
        ...

    @property
    def color(self) -> bool:
        """Whether ``mode=stdout`` uses ANSI colours."""
        ...

    @property
    def quiet(self) -> Sequence[str]:
        """Loggers silenced completely."""
        ...

    @property
    def loggers(self) -> Mapping[str, str]:
        """Per-logger level overrides, applied after ``quiet``."""
        ...


class _StdoutHandler(logging.StreamHandler[TextIO]):
    """Writes to the ``sys.stdout`` that is current when a record is emitted.

    Binding the stream once would send output to a buffer that pytest or a
    reloader has already replaced, so the stream is re-read on every emit.
    """

    def __init__(self) -> None:
        """Starts on the current stdout."""
        super().__init__(stream=sys.stdout)

    def emit(self, record: logging.LogRecord) -> None:
        """Points the handler at the current stdout and writes the record."""
        self.stream = sys.stdout
        super().emit(record)


def _level(level: str) -> int:
    """Maps a level name to the standard library constant, defaulting to INFO."""
    return int(getattr(logging, level.upper(), logging.INFO))


def _shared_processors() -> list[Any]:
    """Returns the processors both logging paths share, renderer excluded."""
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]


def _renderer(settings: LoggingConfig) -> Any:
    """Returns the terminal processor for the configured rendering mode."""
    if settings.mode == "json":
        return structlog.processors.JSONRenderer()
    return stdout_renderer(colors=settings.color)


def _configure_root(processors: list[Any], renderer: Any, level: int) -> None:
    """Replaces the root handler with one that renders both logging paths."""
    global _SAVED_ROOT
    root = logging.getLogger()
    _SAVED_ROOT = (list(root.handlers), root.level)
    formatter = ProcessorFormatter(processor=renderer, foreign_pre_chain=processors)
    handler = _StdoutHandler()
    handler.setFormatter(formatter)
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def _remember(logger: logging.Logger) -> None:
    """Remembers a logger's state once, so :func:`reset_logging` can undo it."""
    if logger.name not in _SAVED_LOGGERS:
        _SAVED_LOGGERS[logger.name] = (list(logger.handlers), logger.propagate, logger.level)


def _detach_uvicorn_loggers() -> None:
    """Routes uvicorn's records through the root handler instead of its own."""
    for name in _UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        _remember(logger)
        logger.handlers.clear()
        logger.propagate = True


def _set_level(name: str, level: int) -> None:
    """Sets one logger's level while remembering its previous one."""
    logger = logging.getLogger(name)
    _remember(logger)
    logger.setLevel(level)


def _apply_logger_levels(settings: LoggingConfig) -> None:
    """Silences the ``quiet`` loggers, then applies the ``loggers`` overrides."""
    for name in settings.quiet:
        _set_level(name, _QUIET_LEVEL)
    for name, level in settings.loggers.items():
        _set_level(name, _level(level))


def configure_logging(settings: LoggingConfig) -> None:
    """Configures structlog and the standard library for the whole process.

    Idempotent: the first call wins, later calls are ignored, so every delivery
    layer can call it defensively.

    Args:
        settings: Level, rendering mode and third-party logger levels.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    level = _level(settings.level)
    processors = _shared_processors()
    _configure_root(processors, _renderer(settings), level)
    structlog.configure(
        processors=[*processors, ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _detach_uvicorn_loggers()
    _apply_logger_levels(settings)
    _CONFIGURED = True


def reset_logging() -> None:
    """Restores the logging state the process had before ``configure_logging``.

    Only meant for tests: the root handlers and levels, the third-party logger
    state and the structlog defaults come back, and the ``get_logger`` cache is
    cleared so the next call binds to the new configuration.
    """
    global _CONFIGURED, _SAVED_ROOT
    root = logging.getLogger()
    if _SAVED_ROOT is not None:
        handlers, level = _SAVED_ROOT
        root.handlers.clear()
        root.handlers.extend(handlers)
        root.setLevel(level)
        _SAVED_ROOT = None
    for name, (handlers, propagate, level) in _SAVED_LOGGERS.items():
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.handlers.extend(handlers)
        logger.propagate = propagate
        logger.setLevel(level)
    _SAVED_LOGGERS.clear()
    _CONFIGURED = False
    structlog.reset_defaults()
    get_logger.cache_clear()
