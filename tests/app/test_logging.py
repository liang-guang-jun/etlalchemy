"""Tests for logging configuration and request logging in the assembly layer."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import structlog
from etlalchemy.app.api.app import create_app
from etlalchemy.app.bootstrap import Container
from etlalchemy.app.bootstrap.lifecycle import run_container
from etlalchemy.app.config.settings import AppSettings
from etlalchemy.shared.logging import configure_logging, get_logger, reset_logging
from fastapi.testclient import TestClient
from structlog.testing import capture_logs


@pytest.fixture(autouse=True)
def _restore_structlog() -> Iterator[None]:
    """Starts and ends every test from the structlog defaults."""
    reset_logging()
    yield
    reset_logging()


def test_app_settings_drive_the_logging_facade(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The assembly settings can be handed to ``configure_logging`` unchanged."""
    configure_logging(AppSettings().logging)

    get_logger("demo").info("hello")

    plain = re.sub(r"\033\[[0-9;]*m", "", capsys.readouterr().out)
    assert "][INFO][demo] hello" in plain


def test_run_container_configures_logging_first(
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared lifecycle configures logging before it wires the container."""
    recorded: list[object] = []
    monkeypatch.setattr(
        "etlalchemy.app.bootstrap.lifecycle.configure_logging",
        lambda settings: recorded.append(settings),
    )
    container = Container()

    async def run() -> None:
        async with run_container(container):
            pass

    asyncio.run(run())

    assert recorded == [container.settings().logging]


def test_request_id_is_generated_and_echoed(config_dir: Path) -> None:
    """A request without the header gets a generated id in the response."""
    with TestClient(create_app()) as client:
        response = client.get("/catalog/catalogs")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]


def test_caller_request_id_is_preserved(config_dir: Path) -> None:
    """The caller's request id travels back unchanged."""
    with TestClient(create_app()) as client:
        response = client.get("/catalog/catalogs", headers={"X-Request-ID": "abc-123"})

    assert response.headers["X-Request-ID"] == "abc-123"


def test_request_ids_differ_between_requests(config_dir: Path) -> None:
    """Every request gets its own id when the caller does not send one."""
    with TestClient(create_app()) as client:
        first = client.get("/catalog/catalogs").headers["X-Request-ID"]
        second = client.get("/catalog/catalogs").headers["X-Request-ID"]

    assert first != second


def settings(**overrides: Any) -> SimpleNamespace:
    """Returns logging settings that keep every level visible."""
    values: dict[str, Any] = {
        "level": "DEBUG",
        "mode": "json",
        "color": False,
        "quiet": [],
        "loggers": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_read_requests_are_logged(config_dir: Path) -> None:
    """A read served straight from the view still produces an access line."""
    configure_logging(settings())

    with capture_logs(
        processors=[structlog.contextvars.merge_contextvars]
    ) as logs, TestClient(create_app()) as client:
        assert client.get("/catalog/catalogs").status_code == 200

    request = next(
        entry
        for entry in logs
        if entry["event"] == "request" and entry["path"] == "/catalog/catalogs"
    )
    assert request["method"] == "GET"
    assert request["status"] == 200
    assert request["request_id"]
    assert "duration_ms" in request


def test_write_requests_are_logged_too(config_dir: Path) -> None:
    """The access line is emitted for commands as well, next to their use-case logs."""
    configure_logging(settings())

    with capture_logs(
        processors=[structlog.contextvars.merge_contextvars]
    ) as logs, TestClient(create_app()) as client:
        assert client.post("/catalog/catalogs", params={"name": "analytics"}).status_code == 200

    events = [entry["event"] for entry in logs]
    assert "catalog.create done" in events
    request = next(entry for entry in logs if entry["event"] == "request")
    assert request["method"] == "POST"
