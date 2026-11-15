"""Tests for the permission-to-scope mapping."""

from __future__ import annotations

import pytest

from etlalchemy.app.auth.scopes import permission_to_scope, scope_covers
from etlalchemy.iam.aggregates.types import Permission


@pytest.mark.parametrize(
    ("permission", "expected"),
    [
        (Permission(resource="*", action="*"), "*"),
        (Permission(resource="catalog", action="*"), "catalog:*"),
        (Permission(resource="doc", action="read"), "doc:read"),
    ],
)
def test_permission_to_scope_renders_resource_and_action(
    permission: Permission,
    expected: str,
) -> None:
    """A permission renders as its scope string, with wildcards preserved."""
    assert permission_to_scope(permission) == expected


@pytest.mark.parametrize(
    ("scopes", "required", "expected"),
    [
        (frozenset(), "catalog:write", False),
        (frozenset({"*"}), "catalog:write", True),
        (frozenset({"catalog:*"}), "catalog:write", True),
        (frozenset({"catalog:*"}), "semantic:write", False),
        (frozenset({"catalog:write"}), "catalog:write", True),
        (frozenset({"catalog:read"}), "catalog:write", False),
    ],
)
def test_scope_covers_matches_exactly_or_through_a_wildcard(
    scopes: frozenset[str],
    required: str,
    expected: bool,
) -> None:
    """``*`` covers everything and ``resource:*`` covers its resource only."""
    assert scope_covers(scopes, required) is expected
