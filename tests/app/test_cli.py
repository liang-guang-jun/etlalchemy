"""Tests for the ``etla`` command line tool."""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from etlalchemy import __version__
from etlalchemy.app.cli.main import app
from etlalchemy.app.config.loader import CONFIG_FILES_ENV, load_settings
from typer.testing import CliRunner

_ENV_KEYS = (
    CONFIG_FILES_ENV,
    "ETLALCHEMY_ENV",
    "ETLALCHEMY_API__HOST",
    "ETLALCHEMY_API__PORT",
)


@pytest.fixture(autouse=True)
def restore_environment() -> Iterator[None]:
    """Restores the environment variables the CLI exports."""
    saved = {key: os.environ.get(key) for key in _ENV_KEYS}
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture
def runner() -> CliRunner:
    """Returns a CLI runner."""
    return CliRunner()


@pytest.fixture
def uvicorn_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Captures the arguments the CLI passes to uvicorn."""
    calls: dict[str, Any] = {}

    def fake_run(topic: str, **kwargs: Any) -> None:
        calls["topic"] = topic
        calls.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    return calls


def write_config(directory: Path, name: str, text: str) -> Path:
    """Writes a configuration file and returns its path."""
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def test_version_is_printed(runner: CliRunner) -> None:
    """``--version`` prints the package version."""
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_lists_the_server_command(runner: CliRunner) -> None:
    """The root help lists the server command."""
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "server" in result.output


def test_server_help_lists_the_config_option(runner: CliRunner) -> None:
    """The server help documents the repeatable config option."""
    result = runner.invoke(app, ["server", "--help"])

    assert result.exit_code == 0
    assert "--config" in result.output
    assert "--reload" in result.output


def test_later_config_file_overrides_earlier_one(
    runner: CliRunner,
    config_dir: Path,
    uvicorn_calls: dict[str, Any],
) -> None:
    """Repeated ``--config`` files are merged in order, so the last one wins."""
    first = write_config(config_dir, "first.yaml", "api:\n  host: 1.2.3.4\n  port: 9000\n")
    second = write_config(config_dir, "second.yaml", "api:\n  port: 9100\n")

    result = runner.invoke(
        app,
        ["server", "--config", str(first), "--config", str(second)],
    )

    assert result.exit_code == 0
    assert uvicorn_calls["host"] == "1.2.3.4"
    assert uvicorn_calls["port"] == 9100
    assert uvicorn_calls["topic"] == "etlalchemy.app.main:app"
    assert uvicorn_calls["reload"] is False
    assert uvicorn_calls["reload_includes"] is None


def test_later_config_file_keeps_sibling_settings(
    runner: CliRunner,
    config_dir: Path,
    uvicorn_calls: dict[str, Any],
) -> None:
    """Files are merged deeply: an overlay only replaces the keys it sets."""
    first = write_config(
        config_dir,
        "first.yaml",
        "api:\n  port: 9000\ncatalog:\n  projection:\n    enabled: true\n",
    )
    second = write_config(config_dir, "second.yaml", "catalog:\n  projection:\n    enabled: false\n")

    result = runner.invoke(app, ["server", "--config", str(first), "--config", str(second)])

    assert result.exit_code == 0
    assert uvicorn_calls["port"] == 9000
    assert load_settings("test").catalog.projection.enabled is False


def test_command_line_options_win_over_config_files(
    runner: CliRunner,
    config_dir: Path,
    uvicorn_calls: dict[str, Any],
) -> None:
    """``--host``, ``--port`` and ``--reload`` override the resolved settings."""
    path = write_config(config_dir, "server.yaml", "api:\n  host: 1.2.3.4\n  port: 9000\n")

    result = runner.invoke(
        app,
        [
            "server",
            "--config",
            str(path),
            "--host",
            "0.0.0.0",
            "--port",
            "8123",
            "--reload",
            "--log-level",
            "debug",
        ],
    )

    assert result.exit_code == 0
    assert uvicorn_calls["host"] == "0.0.0.0"
    assert uvicorn_calls["port"] == 8123
    assert uvicorn_calls["reload"] is True
    assert "*.yaml" in uvicorn_calls["reload_includes"]
    assert uvicorn_calls["log_level"] == "debug"
    assert uvicorn_calls["workers"] == 1


def test_no_reload_flag_disables_reload(
    runner: CliRunner,
    config_dir: Path,
    uvicorn_calls: dict[str, Any],
) -> None:
    """``--no-reload`` wins over ``api.debug`` from the configuration."""
    path = write_config(config_dir, "debug.yaml", "api:\n  debug: true\n")

    result = runner.invoke(app, ["server", "--config", str(path), "--no-reload"])

    assert result.exit_code == 0
    assert uvicorn_calls["reload"] is False


def test_reload_defaults_to_the_debug_setting(
    runner: CliRunner,
    config_dir: Path,
    uvicorn_calls: dict[str, Any],
) -> None:
    """Without a reload flag the ``api.debug`` setting decides."""
    path = write_config(config_dir, "debug.yaml", "api:\n  debug: true\n")

    result = runner.invoke(app, ["server", "--config", str(path)])

    assert result.exit_code == 0
    assert uvicorn_calls["reload"] is True


def test_workers_are_passed_to_uvicorn(
    runner: CliRunner,
    config_dir: Path,
    uvicorn_calls: dict[str, Any],
) -> None:
    """A worker count is forwarded when reload is disabled."""
    result = runner.invoke(app, ["server", "--workers", "2"])

    assert result.exit_code == 0
    assert uvicorn_calls["workers"] == 2


def test_workers_are_rejected_with_reload(
    runner: CliRunner,
    config_dir: Path,
) -> None:
    """Reload and multiple workers cannot be combined."""
    result = runner.invoke(app, ["server", "--reload", "--workers", "2"])

    assert result.exit_code != 0
    assert "cannot be combined" in result.output


def test_config_files_are_exported_for_reloaded_workers(
    runner: CliRunner,
    config_dir: Path,
    uvicorn_calls: dict[str, Any],
) -> None:
    """The resolved files are exported so a reloaded worker reads them too."""
    first = write_config(config_dir, "first.yaml", "api:\n  port: 9000\n")
    second = write_config(config_dir, "second.yaml", "api:\n  port: 9100\n")

    result = runner.invoke(app, ["server", "--config", str(first), "--config", str(second)])

    assert result.exit_code == 0
    exported = os.environ[CONFIG_FILES_ENV].split(os.pathsep)
    assert exported == [str(first), str(second)]


def test_missing_config_file_is_reported(
    runner: CliRunner,
    config_dir: Path,
) -> None:
    """A config file that does not exist fails before uvicorn starts."""
    result = runner.invoke(
        app,
        ["server", "--config", str(config_dir / "missing.yaml")],
    )

    assert result.exit_code != 0
    assert "not found" in result.output
