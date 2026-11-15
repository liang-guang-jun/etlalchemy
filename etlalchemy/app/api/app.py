"""HTTP application factory for the ETLAlchemy API."""

from __future__ import annotations

from dependency_injector import providers
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastmcp.utilities.lifespan import combine_lifespans

from etlalchemy.app.api.logging import RequestLoggingMiddleware
from etlalchemy.app.api.routes.agent import (
    add_exception_handlers as add_agent_exception_handlers,
)
from etlalchemy.app.api.routes.agent import (
    router as agent_router,
)
from etlalchemy.app.api.routes.catalog import (
    add_exception_handlers as add_catalog_exception_handlers,
)
from etlalchemy.app.api.routes.catalog import (
    router as catalog_router,
)
from etlalchemy.app.api.routes.comment import (
    add_exception_handlers as add_comment_exception_handlers,
)
from etlalchemy.app.api.routes.comment import (
    router as comment_router,
)
from etlalchemy.app.api.routes.iam import (
    add_exception_handlers as add_iam_exception_handlers,
)
from etlalchemy.app.api.routes.iam import (
    router as iam_router,
)
from etlalchemy.app.api.routes.ingestion import (
    add_exception_handlers as add_ingestion_exception_handlers,
)
from etlalchemy.app.api.routes.ingestion import (
    router as ingestion_router,
)
from etlalchemy.app.api.routes.semantic import (
    add_exception_handlers as add_semantic_exception_handlers,
)
from etlalchemy.app.api.routes.semantic import (
    router as semantic_router,
)
from etlalchemy.app.api.routes.vocabulary import (
    add_exception_handlers as add_vocabulary_exception_handlers,
)
from etlalchemy.app.api.routes.vocabulary import (
    router as vocabulary_router,
)
from etlalchemy.app.bootstrap import Container, api_lifespan
from etlalchemy.app.mcp.server import MCPServer
from etlalchemy.shared.logging import get_logger

MCP_PATH = "/mcp"
"""Mount point of the MCP server."""


def create_app(container: Container | None = None) -> FastAPI:
    """Creates the HTTP application, mounts the MCP server and attaches the container."""
    container = container or Container()
    # One FastMCP instance backs both paths: this route serves it and the
    # in-process agent transport calls it, so every mounted tool is literally
    # the same object. Registering it on the container keeps the wiring lazy
    # for containers that never build an HTTP application.
    mcp_server = MCPServer(container)
    container.mcp_server.override(providers.Object(mcp_server))
    mcp_app = mcp_server.mcp.http_app(path=MCP_PATH)

    app = FastAPI(
        title="ETLAlchemy",
        lifespan=combine_lifespans(api_lifespan, mcp_app.lifespan),
    )
    app.add_middleware(RequestLoggingMiddleware)
    cors_origins = container.settings().api.cors_origins
    if cors_origins:
        # Added last so it is the outermost middleware: a preflight is answered
        # before the request logger and before any route dependency runs.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cors_origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.container = container  # type: ignore[attr-defined]
    app.mcp_server = mcp_server  # type: ignore[attr-defined]
    add_catalog_exception_handlers(app)
    add_comment_exception_handlers(app)
    add_iam_exception_handlers(app)
    add_ingestion_exception_handlers(app)
    add_semantic_exception_handlers(app)
    add_vocabulary_exception_handlers(app)
    add_agent_exception_handlers(app)
    app.include_router(catalog_router)
    app.include_router(comment_router)
    app.include_router(iam_router)
    app.include_router(ingestion_router)
    app.include_router(semantic_router)
    app.include_router(vocabulary_router)
    app.include_router(agent_router)
    # Add the MCP routes after the HTTP routes so they cannot shadow them, and
    # append them directly instead of mounting: a mount at "/mcp" redirects the
    # bare endpoint to "/mcp/" before the MCP handshake can reject the request.
    app.router.routes.extend(mcp_app.routes)
    get_logger("etlalchemy.api").debug(
        "api.app.created",
        mcp_path=MCP_PATH,
        contexts=[context.name for context in mcp_server.contexts],
    )
    return app
