"""Mapping between IAM permissions and the flat scopes MCP clients see."""

from __future__ import annotations

from etlalchemy.iam.aggregates.types import Permission

__all__ = ["permission_to_scope", "scope_covers"]


def permission_to_scope(permission: Permission) -> str:
    """Renders a permission as a scope string.

    A permission that already contains wildcards keeps them, so the system
    administrator permission ``*:*`` becomes the scope ``*`` and a resource-wide
    grant ``catalog:*`` stays ``catalog:*``.

    Args:
        permission: Permission to render.

    Returns:
        The scope string, for example ``doc:read``.
    """
    if permission.resource == "*" and permission.action == "*":
        return "*"
    return f"{permission.resource}:{permission.action}"


def scope_covers(scopes: frozenset[str], required: str) -> bool:
    """Returns whether one of the scopes grants the required scope.

    ``*`` covers everything, ``resource:*`` covers every action of that resource,
    and otherwise the match is exact.

    Args:
        scopes: Scopes held by the caller.
        required: Scope the caller needs.

    Returns:
        ``True`` when the caller holds a covering scope.
    """
    if "*" in scopes or required in scopes:
        return True
    resource, _separator, _action = required.partition(":")
    return f"{resource}:*" in scopes
