"""IAM context MCP tools.

The IAM surface is deliberately read only: writes need a session, and an MCP tool
has no request context to carry one.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.schemas.iam import (
    ApiKeyResponse,
    AuditResponse,
    GroupMemberResponse,
    GroupResponse,
    ProviderResponse,
    TenantResponse,
    UserResponse,
)
from etlalchemy.shared.utils import uuid_or_none

READ_ONLY = {"readOnlyHint": True}
"""Annotation shared by every IAM tool."""


def register(mcp: FastMCP, container: Container) -> None:
    """Registers the IAM tools on the given server."""

    @mcp.tool(
        name="list_tenants",
        description="List the live tenants.",
        annotations=READ_ONLY,
    )
    async def list_tenants() -> list[TenantResponse]:
        """Return every live tenant."""
        rows = await container.iam_view().list_tenants()
        return [TenantResponse.from_row(row) for row in rows]

    @mcp.tool(
        name="list_users",
        description="List the live users.",
        annotations=READ_ONLY,
    )
    async def list_users() -> list[UserResponse]:
        """Return every live user."""
        rows = await container.iam_view().list_users()
        return [UserResponse.from_row(row) for row in rows]

    @mcp.tool(
        name="get_user",
        description="Return one live user, or null when it does not exist.",
        annotations=READ_ONLY,
    )
    async def get_user(
        user_id: Annotated[str, Field(description="ID of the user.")],
    ) -> UserResponse | None:
        """Return one user by id."""
        identifier = uuid_or_none(user_id)
        if identifier is None:
            return None
        row = await container.iam_view().get_user(identifier)
        return None if row is None else UserResponse.from_row(row)

    @mcp.tool(
        name="list_groups",
        description="List the live groups of a tenant.",
        annotations=READ_ONLY,
    )
    async def list_groups(
        tenant_id: Annotated[str, Field(description="ID of the tenant.")],
    ) -> list[GroupResponse]:
        """Return the groups of a tenant."""
        identifier = uuid_or_none(tenant_id)
        if identifier is None:
            return []
        rows = await container.iam_view().list_groups(identifier)
        return [GroupResponse.from_row(row) for row in rows]

    @mcp.tool(
        name="list_group_members",
        description="List the members of a group, optionally including its subgroups.",
        annotations=READ_ONLY,
    )
    async def list_group_members(
        group_id: Annotated[str, Field(description="ID of the group.")],
        recursive: Annotated[
            bool,
            Field(description="Whether the members of the subgroups are included."),
        ] = False,
    ) -> list[GroupMemberResponse]:
        """Return the members of one group."""
        view = container.iam_view()
        identifier = uuid_or_none(group_id)
        if identifier is None:
            return []
        group = await view.get_group(identifier)
        if group is None:
            return []
        rows = await view.list_group_members(group.tenant_id)
        if recursive:
            groups = await view.list_groups(group.tenant_id)
            included = {identifier}
            pending = [identifier]
            while pending:
                current = pending.pop()
                for row in groups:
                    if row.parent_group_id == current and row.group_id not in included:
                        included.add(row.group_id)
                        pending.append(row.group_id)
            rows = [row for row in rows if row.group_id in included]
        else:
            rows = [row for row in rows if row.group_id == identifier]
        return [GroupMemberResponse.from_row(row) for row in rows]

    @mcp.tool(
        name="list_api_keys",
        description="List the API keys of a user; the secret and its hash are never returned.",
        annotations=READ_ONLY,
    )
    async def list_api_keys(
        user_id: Annotated[str, Field(description="ID of the user.")],
    ) -> list[ApiKeyResponse]:
        """Return the API keys of a user."""
        identifier = uuid_or_none(user_id)
        if identifier is None:
            return []
        rows = await container.iam_view().list_api_keys(identifier)
        return [ApiKeyResponse.from_row(row) for row in rows]

    @mcp.tool(
        name="list_auth_providers",
        description="List the live auth providers; only a has_secret flag is returned.",
        annotations=READ_ONLY,
    )
    async def list_auth_providers() -> list[ProviderResponse]:
        """Return every live auth provider."""
        rows = await container.iam_view().list_providers()
        return [ProviderResponse.from_row(row) for row in rows]

    @mcp.tool(
        name="list_audit_events",
        description="List audit records, newest first.",
        annotations=READ_ONLY,
    )
    async def list_audit_events(
        limit: Annotated[int, Field(description="Maximum number of records.")] = 50,
        offset: Annotated[int, Field(description="Number of records to skip.")] = 0,
        action: Annotated[
            str | None,
            Field(description="Only records with this action, for example authorize.denied."),
        ] = None,
    ) -> list[AuditResponse]:
        """Return audit records."""
        rows = await container.iam_view().list_audit_events(
            limit=limit,
            offset=offset,
            action=action,
        )
        return [AuditResponse.from_row(row) for row in rows]
