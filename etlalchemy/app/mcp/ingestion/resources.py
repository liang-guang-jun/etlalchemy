"""Ingestion context MCP resources.

Every resource returns ``application/json`` text. Reading a resource never fails
because an object is missing: unknown or malformed references answer ``null`` or
``[]``.
"""

from __future__ import annotations

from dataclasses import asdict

from fastmcp import FastMCP

from etlalchemy.app.bootstrap import Container
from etlalchemy.shared.utils import dump, uuid_or_none


def register(mcp: FastMCP, container: Container) -> None:
    """Registers the ingestion resources on the given server."""

    @mcp.resource(
        "ingestion:///connections",
        name="all-connections",
        description="All live source connections, ordered by name.",
        mime_type="application/json",
    )
    async def all_connections() -> str:
        """Return every live connection."""
        rows = [asdict(row) for row in await container.ingestion_view().list_connections()]
        return dump(rows)

    @mcp.resource(
        "ingestion:///connections/{connection_id}",
        name="connection",
        description="One live source connection, or null when it does not exist.",
        mime_type="application/json",
    )
    async def connection(connection_id: str) -> str:
        """Return one connection by id."""
        key = uuid_or_none(connection_id)
        row = None if key is None else await container.ingestion_view().get_connection(key)
        return dump(None if row is None else asdict(row))

    @mcp.resource(
        "ingestion:///runs",
        name="all-import-runs",
        description="All import runs, ordered by creation.",
        mime_type="application/json",
    )
    async def all_import_runs() -> str:
        """Return every import run."""
        rows = [asdict(row) for row in await container.ingestion_view().list_import_runs()]
        return dump(rows)

    @mcp.resource(
        "ingestion:///runs/{run_id}",
        name="import-run",
        description="One import run, or null when it does not exist.",
        mime_type="application/json",
    )
    async def import_run(run_id: str) -> str:
        """Return one import run by id."""
        key = uuid_or_none(run_id)
        row = None if key is None else await container.ingestion_view().get_import_run(key)
        return dump(None if row is None else asdict(row))
