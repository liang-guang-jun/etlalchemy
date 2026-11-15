"""Tests for the staged app source."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from etlalchemy.app.deploy.errors import DeployError
from etlalchemy.app.deploy.staging import StagingSpec, build_staging

from .support import make_repo


def spec(root: Path, **overrides: Any) -> StagingSpec:
    """Returns a staging spec pointing at a miniature repository."""
    values: dict[str, Any] = {
        "source": root,
        "ui_dir": root / "dist" / "ui",
        "config_files": (),
        "command": ("uv", "run", "uvicorn", "etlalchemy.app.main:app"),
        "health_timeout_seconds": 90,
    }
    values.update(overrides)
    return StagingSpec(**values)


def test_staging_writes_the_package_bundle_and_app_yaml(tmp_path: Path) -> None:
    """The platform receives everything its build and its runtime need."""
    root = make_repo(tmp_path / "repo")
    target = tmp_path / "staging"
    target.mkdir()

    staged = build_staging(spec(root), target)

    assert (target / "etlalchemy" / "__init__.py").is_file()
    assert (target / "dist" / "ui" / "index.html").is_file()
    assert (target / "uv.lock").is_file()
    assert staged.config_names == ("config.default.yaml",)
    document = yaml.safe_load((target / "app.yaml").read_text(encoding="utf-8"))
    assert document["command"] == ["uv", "run", "uvicorn", "etlalchemy.app.main:app"]
    assert document["health_check"] == {"path": "/health", "timeout_seconds": 90}
    assert document["env"] == [
        {"name": "ETLALCHEMY_CONFIG_FILES", "value": "config.default.yaml"},
    ]


def test_staging_disables_the_default_dependency_groups(tmp_path: Path) -> None:
    """The platform build must not install the linters and the test suite."""
    root = make_repo(tmp_path / "repo")
    target = tmp_path / "staging"
    target.mkdir()

    build_staging(spec(root), target)

    text = (target / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.uv]" in text
    assert "default-groups = []" in text


def test_configuration_files_keep_the_merge_order(tmp_path: Path) -> None:
    """A later ``--config`` file is listed after the default one."""
    root = make_repo(tmp_path / "repo")
    extra = tmp_path / "config.prod.yaml"
    extra.write_text("logging:\n  level: WARNING\n", encoding="utf-8")
    target = tmp_path / "staging"
    target.mkdir()

    staged = build_staging(spec(root, config_files=(extra,)), target)

    assert staged.config_names == ("config.default.yaml", "config.prod.yaml")
    document = yaml.safe_load((target / "app.yaml").read_text(encoding="utf-8"))
    assert document["env"][0]["value"] == os.pathsep.join(
        ("config.default.yaml", "config.prod.yaml"),
    )


def test_two_configuration_files_with_one_name_are_rejected(tmp_path: Path) -> None:
    """A collision would silently upload only one of the two files."""
    root = make_repo(tmp_path / "repo")
    first = tmp_path / "a" / "config.prod.yaml"
    second = tmp_path / "b" / "config.prod.yaml"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("logging: {}\n", encoding="utf-8")
    second.write_text("logging: {}\n", encoding="utf-8")
    target = tmp_path / "staging"
    target.mkdir()

    with pytest.raises(DeployError, match="named config.prod.yaml"):
        build_staging(spec(root, config_files=(first, second)), target)


def test_missing_bundle_is_reported(tmp_path: Path) -> None:
    """An unbuilt frontend fails before anything is uploaded."""
    root = make_repo(tmp_path / "repo")
    (root / "dist" / "ui" / "index.html").unlink()
    target = tmp_path / "staging"
    target.mkdir()

    with pytest.raises(DeployError, match="frontend bundle is missing"):
        build_staging(spec(root), target)


def test_inline_secrets_and_sqlite_are_reported(tmp_path: Path) -> None:
    """The operator sees what would leak and what would be lost."""
    root = make_repo(tmp_path / "repo", backend="sqlite")
    (root / "config.default.yaml").write_text(
        "database:\n  backend: sqlite\n  sqlite_path: ./app.db\n"
        'cipher_key: "c2VjcmV0"\n'
        "agent:\n  llm:\n    credential_ref: env:DBX_TOKEN\n",
        encoding="utf-8",
    )
    target = tmp_path / "staging"
    target.mkdir()

    staged = build_staging(spec(root), target)

    assert any("cipher_key" in warning for warning in staged.warnings)
    assert any("sqlite" in warning for warning in staged.warnings)
    assert not any("DBX_TOKEN" in warning for warning in staged.warnings)


def test_postgres_configuration_has_no_database_warning(tmp_path: Path) -> None:
    """A Postgres or Lakebase DSN keeps the event store across restarts."""
    root = make_repo(tmp_path / "repo")
    target = tmp_path / "staging"
    target.mkdir()

    staged = build_staging(spec(root), target)

    assert not any("sqlite" in warning for warning in staged.warnings)
