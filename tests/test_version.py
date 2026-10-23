"""Tests for version consistency."""

import tomllib
from pathlib import Path

import etlalchemy

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_version_matches_pyproject() -> None:
    """Package __version__ must match project.version in pyproject.toml."""
    with PYPROJECT.open("rb") as f:
        project_version = tomllib.load(f)["project"]["version"]

    assert etlalchemy.__version__ == project_version
