"""Serving the HTTP API from the command line.

The module resolves the layered configuration once, exports the command line
choices to the environment and then hands control to uvicorn, so a reloaded
worker imports the same configuration as the process that started it.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from etlalchemy.app.config.loader import CONFIG_FILES_ENV, load_settings
from etlalchemy.shared.logging import configure_logging, get_logger

ENV_VAR = "ETLALCHEMY_ENV"
HOST_VAR = "ETLALCHEMY_API__HOST"
PORT_VAR = "ETLALCHEMY_API__PORT"

APP_TOPIC = "etlalchemy.app.main:app"
"""Import string of the FastAPI application; uvicorn needs it to reload."""


def export_config_files(config_files: Sequence[Path]) -> None:
    """Exports the configuration files so reloaded workers read the same ones."""
    if config_files:
        os.environ[CONFIG_FILES_ENV] = os.pathsep.join(str(path) for path in config_files)


def run_server(
    config_files: Sequence[str | Path] = (),
    *,
    env: str | None = None,
    host: str | None = None,
    port: int | None = None,
    reload: bool | None = None,
    log_level: str | None = None,
    workers: int | None = None,
) -> None:
    """Serves the HTTP API with uvicorn, applying the command line options last.

    The configuration files are merged in order, so a later file overrides an
    earlier one. ``--host``, ``--port`` and ``--reload`` override the resolved
    ``api`` settings; ``--reload`` defaults to ``api.debug``.
    """
    files = [Path(path).expanduser().resolve() for path in config_files]
    export_config_files(files)
    if env is not None:
        os.environ[ENV_VAR] = env
    if host is not None:
        os.environ[HOST_VAR] = host
    if port is not None:
        os.environ[PORT_VAR] = str(port)

    settings = load_settings(env=env, config_files=files)
    configure_logging(settings.logging)
    get_logger("etlalchemy.cli").info(
        "server.configured",
        env=env,
        config_files=[str(path) for path in files],
        host=settings.api.host,
        port=settings.api.port,
        mode=settings.logging.mode,
        level=settings.logging.level,
    )
    serve(
        host=settings.api.host,
        port=settings.api.port,
        reload=settings.api.debug if reload is None else reload,
        log_level=log_level,
        workers=workers,
    )


def serve(
    *,
    host: str,
    port: int,
    reload: bool,
    log_level: str | None,
    workers: int | None,
) -> None:
    """Runs the API application with uvicorn on the given address."""
    import uvicorn

    log = get_logger("etlalchemy.cli")
    worker_count = 1 if reload else workers
    log.info(
        "server.start",
        host=host,
        port=port,
        reload=reload,
        workers=worker_count,
        log_level=log_level,
    )
    uvicorn.run(
        APP_TOPIC,
        host=host,
        port=port,
        reload=reload,
        # ``--reload`` watches Python by default; also watch the YAML layers so
        # editing ``config.default.yaml`` restarts the worker and re-reads the
        # configuration (the LLM provider bootstrap then synchronises it).
        reload_includes=["*.py", "*.yaml", "*.yml"] if reload else None,
        # uvicorn must not install its own handlers or formatter: its records
        # propagate to the root handler that ``configure_logging`` installed.
        log_config=None,
        log_level=log_level,
        workers=worker_count,
    )
    log.info("server.stopped")
