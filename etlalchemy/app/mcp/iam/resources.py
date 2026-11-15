"""IAM context MCP resources.

Every resource answers ``application/json`` text and returns ``null`` or ``[]``
instead of raising when an id is unknown or malformed.
"""

from __future__ import annotations

from fastmcp import FastMCP

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.schemas.iam import (
    AuditResponse,
    GroupResponse,
    ProviderResponse,
    TenantResponse,
    UserResponse,
)
from etlalchemy.shared.utils import dump, uuid_or_none


def register(mcp: FastMCP, container: Container) -> None:
    """Registers the IAM resources on the given server."""

    @mcp.resource(
        "iam:///tenants",
        name="iam-tenants",
        description="Every live tenant.",
        mime_type="application/json",
    )
    async def tenants() -> str:
        """Return every live tenant."""
        rows = [TenantResponse.from_row(row) for row in await container.iam_view().list_tenants()]
        return dump([row.model_dump(mode="json") for row in rows])

    @mcp.resource(
        "iam:///users",
        name="iam-users",
        description="Every live user.",
        mime_type="application/json",
    )
    async def users() -> str:
        """Return every live user."""
        rows = [UserResponse.from_row(row) for row in await container.iam_view().list_users()]
        return dump([row.model_dump(mode="json") for row in rows])

    @mcp.resource(
        "iam:///users/{user_id}",
        name="iam-user",
        description="One live user, or null when it does not exist.",
        mime_type="application/json",
    )
    async def user(user_id: str) -> str:
        """Return one user by id."""
        identifier = uuid_or_none(user_id)
        row = None if identifier is None else await container.iam_view().get_user(identifier)
        if row is None:
            return dump(None)
        return dump(UserResponse.from_row(row).model_dump(mode="json"))

    @mcp.resource(
        "iam:///groups/{tenant_id}",
        name="iam-groups",
        description="The live groups of a tenant.",
        mime_type="application/json",
    )
    async def groups(tenant_id: str) -> str:
        """Return the groups of one tenant."""
        identifier = uuid_or_none(tenant_id)
        rows = [] if identifier is None else await container.iam_view().list_groups(identifier)
        return dump([GroupResponse.from_row(row).model_dump(mode="json") for row in rows])

    @mcp.resource(
        "iam:///providers",
        name="iam-providers",
        description="Every live auth provider; the secret reference is hidden.",
        mime_type="application/json",
    )
    async def providers() -> str:
        """Return every live auth provider."""
        rows = [
            ProviderResponse.from_row(row) for row in await container.iam_view().list_providers()
        ]
        return dump([row.model_dump(mode="json") for row in rows])

    @mcp.resource(
        "iam:///audit",
        name="iam-audit",
        description="The 100 newest audit records.",
        mime_type="application/json",
    )
    async def audit() -> str:
        """Return the newest audit records."""
        rows = [
            AuditResponse.from_row(row)
            for row in await container.iam_view().list_audit_events(limit=100)
        ]
        return dump([row.model_dump(mode="json") for row in rows])
