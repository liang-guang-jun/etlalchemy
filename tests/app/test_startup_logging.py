"""Tests for the startup trail the process logs itself.

uvicorn's own startup records are not a reliable progress report: they are
filtered by ``logging.quiet`` and, under ``--reload``, the child process only
configures logging once the lifespan starts. The assembly layers therefore log
their own start and stop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import uvicorn
from etlalchemy.app.bootstrap import Container
from etlalchemy.app.bootstrap.lifecycle import run_container
from etlalchemy.app.cli.server import serve
from etlalchemy.shared.logging import configure_logging, reset_logging
from structlog.testing import capture_logs


def settings(**overrides: Any) -> SimpleNamespace:
    """Returns logging settings that keep the debug trail visible."""
    values: dict[str, Any] = {
        "level": "DEBUG",
        "mode": "stdout",
        "color": False,
        "quiet": [],
        "loggers": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture(autouse=True)
def _logging() -> Iterator[None]:
    """Configures logging once and restores the process state afterwards."""
    reset_logging()
    configure_logging(settings())
    yield
    reset_logging()


def test_run_container_logs_its_lifecycle(config_dir: Path) -> None:
    """The container start and stop are visible without uvicorn's own lines."""

    async def run() -> None:
        async with run_container(Container()):
            pass

    with capture_logs() as logs:
        asyncio.run(run())

    events = [entry["event"] for entry in logs]
    assert events[0] == "lifecycle.start"
    assert logs[0]["contexts"] == [
        "catalog",
        "iam",
        "ingestion",
        "semantic",
        "vocabulary",
        "comment",
        "llm_config",
        "conversation",
    ]
    assert "lifecycle.resources.started" in events
    assert events[-1] == "lifecycle.stopped"


def test_run_container_logs_each_read_model(config_dir: Path) -> None:
    """Every context reports its read model before the resources start."""

    async def run() -> None:
        async with run_container(Container()):
            pass

    with capture_logs() as logs:
        asyncio.run(run())

    ready = [entry["context"] for entry in logs if entry["event"] == "lifecycle.read_model.ready"]
    assert ready == [
        "catalog",
        "iam",
        "ingestion",
        "semantic",
        "vocabulary",
        "comment",
        "llm_config",
        "conversation",
    ]


def test_serve_logs_start_and_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI reports the address it hands to uvicorn and the shutdown."""
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)

    with capture_logs() as logs:
        serve(host="127.0.0.1", port=8000, reload=False, log_level=None, workers=2)

    assert [entry["event"] for entry in logs] == ["server.start", "server.stopped"]
    assert logs[0]["host"] == "127.0.0.1"
    assert logs[0]["port"] == 8000
    assert logs[0]["workers"] == 2


def test_serve_reports_the_single_reload_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--reload`` runs exactly one worker, and the log says so."""
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)

    with capture_logs() as logs:
        serve(host="127.0.0.1", port=8000, reload=True, log_level=None, workers=4)

    assert logs[0]["workers"] == 1
    assert logs[0]["reload"] is True
