"""English workflow prompts for the IAM context."""

from __future__ import annotations

from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Registers the IAM prompts on the given server."""

    @mcp.prompt(
        name="iam-access-review",
        description="Review who can act inside a tenant and why.",
    )
    def access_review(
        tenant_id: str,
    ) -> str:
        """Return the access review workflow template."""
        return f"""
The user wants an access review of the tenant `{tenant_id}`.

1. Read `iam:///tenants` and confirm the tenant exists.
2. Read `iam:///groups/{tenant_id}` to list the groups.
3. For each group, read the group members with the `list_group_members` tool;
   remember that a child group inherits the grants of its ancestors.
4. Read `iam:///audit` and filter the `authorize.denied` records of the tenant.
5. Report, per group, the granted permissions and the users that inherit them,
   and call out groups that grant nothing or users that belong to no group.
Never propose a change to credentials from this review.
"""
