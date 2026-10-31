"""Shared fixtures for the test suite."""

from __future__ import annotations

from collections.abc import Callable

import pytest


@pytest.fixture
def squash() -> Callable[[str], str]:
    """Return a helper that collapses whitespace in a SQL statement."""

    def _squash(sql: str) -> str:
        """Collapse whitespace so assertions survive pretty formatting."""
        return " ".join(sql.split())

    return _squash
