"""Tests for the ``etla iam`` command group."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from etlalchemy.app.cli.main import app
from typer.testing import CliRunner

runner = CliRunner()

PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def clear_session() -> Iterator[None]:
    """Clears ``IAM_SESSION`` so a missing session is really missing."""
    saved = os.environ.pop("IAM_SESSION", None)
    yield
    if saved is not None:
        os.environ["IAM_SESSION"] = saved


def test_bootstrap_status_reports_an_empty_system(config_dir: object) -> None:
    """``bootstrap status`` runs without a session."""
    result = runner.invoke(app, ["iam", "bootstrap", "status"])

    assert result.exit_code == 0
    assert "not initialized" in result.output


def test_bootstrap_admin_creates_the_first_administrator(config_dir: object) -> None:
    """``bootstrap admin`` prompts twice and refuses a second run."""
    first = runner.invoke(
        app,
        ["iam", "bootstrap", "admin", "--email", "root@example.com"],
        input=f"{PASSWORD}\n{PASSWORD}\n",
    )
    assert first.exit_code == 0, first.output

    status = runner.invoke(app, ["iam", "bootstrap", "status"])
    assert "completed" in status.output

    second = runner.invoke(
        app,
        ["iam", "bootstrap", "admin", "--email", "other@example.com"],
        input=f"{PASSWORD}\n{PASSWORD}\n",
    )
    assert second.exit_code == 1


def test_commands_without_a_session_exit_with_three(config_dir: object) -> None:
    """A protected command reports the missing session."""
    result = runner.invoke(app, ["iam", "tenant", "list"])

    assert result.exit_code == 3
    assert "session is required" in result.output


def test_tenant_list_uses_the_session(config_dir: object) -> None:
    """A logged-in session lists the tenants as JSON."""
    created = runner.invoke(
        app,
        ["iam", "bootstrap", "admin", "--email", "root@example.com"],
        input=f"{PASSWORD}\n{PASSWORD}\n",
    )
    assert created.exit_code == 0, created.output

    login = runner.invoke(
        app,
        ["iam", "login", "--email", "root@example.com"],
        input=f"{PASSWORD}\n",
    )
    assert login.exit_code == 0, login.output
    session = login.output.strip().splitlines()[-1]

    tenant = runner.invoke(
        app,
        ["iam", "tenant", "create", "--name", "acme", "--session", session],
    )
    assert tenant.exit_code == 0, tenant.output

    listed = runner.invoke(
        app,
        ["iam", "tenant", "list", "--session", session, "--json"],
    )
    assert listed.exit_code == 0, listed.output
    assert '"name": "acme"' in listed.output
