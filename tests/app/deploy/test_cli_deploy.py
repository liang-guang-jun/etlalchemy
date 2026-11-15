"""Tests for the ``etla deploy`` command."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from etlalchemy.app.cli import deploy as deploy_module
from etlalchemy.app.cli.main import app
from etlalchemy.app.deploy.errors import AppNotFoundError
from etlalchemy.app.deploy.models import DeployPlan, DeployReport


@pytest.fixture
def runner() -> CliRunner:
    """Returns a CLI runner."""
    return CliRunner()


def report(*, dry_run: bool = False) -> DeployReport:
    """Returns the report the patched deployment produces."""
    return DeployReport(
        profile="team",
        host="https://adb-123.azuredatabricks.net",
        app_name="etlalchemy",
        workspace_path="/Workspace/Users/user@example.com/etlalchemy",
        plan=DeployPlan(changes=(), removals=()),
        uploaded=2,
        removed=0,
        bytes_uploaded=10,
        dry_run=dry_run,
        deployment_id="deployment-1",
        state="SUCCEEDED",
        url="https://etlalchemy-123.cloud.databricksapps.com",
    )


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """Patches the deployment entry point and captures its options."""
    state: dict[str, Any] = {}

    def fake(options: Any, *, console: Any) -> DeployReport:
        del console
        state["options"] = options
        return report(dry_run=options.dry_run)

    monkeypatch.setattr(deploy_module, "deploy_databricks_apps", fake)
    yield state


def test_a_target_is_required(config_dir: Path, runner: CliRunner) -> None:
    """Without a target the command explains the only supported one."""
    result = runner.invoke(app, ["deploy"])

    assert result.exit_code == 2
    assert "--databricks-apps" in result.output


def test_help_lists_the_profile_and_target(runner: CliRunner) -> None:
    """The help documents the target flag and the profile option."""
    result = runner.invoke(app, ["deploy", "--help"])

    assert result.exit_code == 0
    assert "--databricks-apps" in result.output
    assert "--profile" in result.output
    assert "--dry-run" in result.output


def test_json_report_is_printed(
    config_dir: Path,
    runner: CliRunner,
    captured: dict[str, Any],
) -> None:
    """``--json`` prints the machine-readable report."""
    result = runner.invoke(
        app,
        ["deploy", "--databricks-apps", "--profile", "team", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["app_name"] == "etlalchemy"
    assert payload["state"] == "SUCCEEDED"
    assert payload["url"].startswith("https://")
    assert captured["options"].profile == "team"
    assert captured["options"].app_name == "etlalchemy"


def test_profile_falls_back_to_the_settings(
    config_dir: Path,
    runner: CliRunner,
    captured: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The configuration layer supplies the default target."""
    monkeypatch.setenv("ETLALCHEMY_DEPLOY__DATABRICKS__PROFILE", "configured")
    monkeypatch.setenv("ETLALCHEMY_DEPLOY__DATABRICKS__APP_NAME", "warehouse")

    result = runner.invoke(app, ["deploy", "--databricks-apps", "--json"])

    assert result.exit_code == 0, result.output
    assert captured["options"].profile == "configured"
    assert captured["options"].app_name == "warehouse"


def test_dry_run_prints_the_hint(
    config_dir: Path,
    runner: CliRunner,
    captured: dict[str, Any],
) -> None:
    """A dry run says that nothing was written."""
    result = runner.invoke(app, ["deploy", "--databricks-apps", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "nothing was uploaded" in result.output


def test_deployment_errors_exit_with_one(
    config_dir: Path,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing app is reported on stderr with a non-zero exit code."""

    def fake(options: Any, *, console: Any) -> DeployReport:
        del options, console
        msg = "the Databricks app 'etlalchemy' does not exist"
        raise AppNotFoundError(msg)

    monkeypatch.setattr(deploy_module, "deploy_databricks_apps", fake)

    result = runner.invoke(app, ["deploy", "--databricks-apps"])

    assert result.exit_code == 1
    assert "does not exist" in result.output
