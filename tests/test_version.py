"""Smoke tests for the package metadata."""

import etlalchemy


def test_version_is_exposed() -> None:
    """The package exposes a non-empty version string."""
    assert isinstance(etlalchemy.__version__, str)
    assert etlalchemy.__version__
