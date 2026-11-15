"""Read-only LLM provider resources.

A resource has no caller identity, so it only exposes public providers; anything
scoped to a user or a tenant is reachable through the tools, which do resolve the
session.
"""

from __future__ import annotations

from fastmcp import FastMCP

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.schemas.agent import ProviderResponse
from etlalchemy.shared.utils import dump, uuid_or_none


def register(mcp: FastMCP, container: Container) -> None:
    """Registers the LLM provider resources on the given server."""

    @mcp.resource(
        "llm:///providers",
        name="llm-providers",
        description="The public LLM providers; private ones need the list tool.",
        mime_type="application/json",
    )
    async def providers() -> str:
        """Return the public providers."""
        rows = await container.llm_config_view().list_providers(is_public=True)
        return dump([ProviderResponse.from_row(row).model_dump(mode="json") for row in rows])

    @mcp.resource(
        "llm:///{provider_id}",
        name="llm-provider",
        description="One public LLM provider, or null when it is not public.",
        mime_type="application/json",
    )
    async def provider(provider_id: str) -> str:
        """Return one public provider, or ``None``."""
        key = uuid_or_none(provider_id)
        if key is None:
            return dump(None)
        row = await container.llm_config_view().get_provider(key)
        if row is None or not row.is_public:
            return dump(None)
        return dump(ProviderResponse.from_row(row).model_dump(mode="json"))
