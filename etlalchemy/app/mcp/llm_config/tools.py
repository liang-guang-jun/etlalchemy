"""Read-only LLM provider tools.

A tool resolves the caller through the MCP session resolver, so it can list the
providers the caller may actually use. Writes stay on the HTTP surface: an agent
that could create a provider could point it at an arbitrary endpoint.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastmcp import FastMCP
from pydantic import Field

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.mcp.errors import mcp_error_guard
from etlalchemy.app.schemas.agent import ProviderResponse


def register(mcp: FastMCP, container: Container) -> None:
    """Registers the LLM provider tools on the given server."""

    @mcp.tool(
        name="list_llm_providers",
        description=(
            "List the LLM providers the caller may run against: owned, shared with "
            "the caller or one of its groups, and public ones."
        ),
        annotations={"readOnlyHint": True},
    )
    async def list_llm_providers(
        include_public: Annotated[
            bool,
            Field(description="Whether public providers are included."),
        ] = True,
        limit: Annotated[
            int | None,
            Field(description="Maximum number of providers to return."),
        ] = None,
        offset: Annotated[int, Field(description="Number of providers to skip.")] = 0,
    ) -> list[ProviderResponse]:
        """List the providers the caller may use."""
        session_id = container.mcp_session_resolver()
        with mcp_error_guard():
            rows = await container.llm_config_application().list_llm_providers(
                session_id,
                include_public=include_public,
                limit=limit,
                offset=offset,
            )
        return [ProviderResponse.from_row(row) for row in rows]

    @mcp.tool(
        name="get_llm_provider",
        description="Return one LLM provider the caller may use, or null.",
        annotations={"readOnlyHint": True},
    )
    async def get_llm_provider(
        provider_id: Annotated[UUID, Field(description="ID of the provider.")],
    ) -> ProviderResponse | None:
        """Return one provider, or ``None`` when it is not visible."""
        session_id = container.mcp_session_resolver()
        with mcp_error_guard():
            try:
                detail = await container.llm_config_application().get_llm_provider(
                    session_id,
                    provider_id,
                )
            except Exception:
                return None
        return ProviderResponse.from_row(detail.provider)
