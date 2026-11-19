"""Tests for the shared adapter option parsing."""

from types import SimpleNamespace
from typing import Any

import pytest
from etlalchemy.ingestion.adapters._options import (
    bool_option,
    int_option,
    json_option,
    type_policy,
)


def connection(**options: str) -> Any:
    """Returns a stand-in connection carrying the given options."""
    return SimpleNamespace(options=options)


def test_type_policy_defaults_to_fail() -> None:
    """A connection without the option uses the strict policy."""
    assert type_policy(connection()) == "fail"


@pytest.mark.parametrize("policy", ["fail", "json", "skip"])
def test_type_policy_accepts_supported_values(policy: str) -> None:
    """The three documented policies are preserved."""
    assert type_policy(connection(type_policy=policy)) == policy


def test_type_policy_falls_back_for_unknown_values() -> None:
    """An unknown policy is treated as ``fail``."""
    assert type_policy(connection(type_policy="nope")) == "fail"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("true", True),
        ("YES", True),
        ("1", True),
        ("on", True),
        ("false", False),
        ("no", False),
        ("0", False),
    ],
)
def test_bool_option_parses_common_spellings(raw: str, expected: bool) -> None:
    """Boolean options accept the usual spellings."""
    assert bool_option(connection(flag=raw), "flag", not expected) is expected


def test_bool_option_uses_the_default() -> None:
    """A missing boolean option falls back to the default."""
    assert bool_option(connection(), "flag", True) is True


def test_int_option_parses_and_falls_back() -> None:
    """Integer options parse numbers and fall back on bad input."""
    assert int_option(connection(n="42"), "n", 7) == 42
    assert int_option(connection(n="bad"), "n", 7) == 7
    assert int_option(connection(), "n", 7) == 7


def test_json_option_parses_objects_only() -> None:
    """JSON options must be objects; anything else becomes ``{}``."""
    assert json_option(connection(overrides='{"order_status": "text"}'), "overrides") == {
        "order_status": "text"
    }
    assert json_option(connection(overrides="not-json"), "overrides") == {}
    assert json_option(connection(overrides="[]"), "overrides") == {}
    assert json_option(connection(), "overrides") == {}
