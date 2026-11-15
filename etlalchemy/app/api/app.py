"""HTTP application factory for the ETLAlchemy API."""

from __future__ import annotations

from pathlib import Path

from dependency_injector import providers
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastmcp.utilities.lifespan import combine_lifespans

from etlalchemy.app.api.dependencies.auth import configure_token_path
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
from etlalchemy.app.api.static import serve_spa
from etlalchemy.app.bootstrap import Container, api_lifespan
from etlalchemy.app.config.loader import find_config_dir
from etlalchemy.app.mcp.server import MCPServer
from etlalchemy.shared.logging import get_logger

MCP_PATH = "/mcp"
"""Mount point of the MCP server."""

DOCS_PATHS: tuple[str, ...] = ("/docs", "/redoc", "/openapi.json")
"""Documentation paths the single-page fallback must never answer for."""


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
    settings = container.settings()
    cors_origins = settings.api.cors_origins
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
    prefix = settings.api.prefix
    configure_token_path(prefix)
    add_catalog_exception_handlers(app)
    add_comment_exception_handlers(app)
    add_iam_exception_handlers(app)
    add_ingestion_exception_handlers(app)
    add_semantic_exception_handlers(app)
    add_vocabulary_exception_handlers(app)
    add_agent_exception_handlers(app)
    app.include_router(catalog_router, prefix=prefix)
    app.include_router(comment_router, prefix=prefix)
    app.include_router(iam_router, prefix=prefix)
    app.include_router(ingestion_router, prefix=prefix)
    app.include_router(semantic_router, prefix=prefix)
    app.include_router(vocabulary_router, prefix=prefix)
    app.include_router(agent_router, prefix=prefix)

    @app.get(settings.api.health_path, include_in_schema=False)
    async def health() -> dict[str, str]:
        """Answers the liveness probe of the hosting platform."""
        return {"status": "ok"}

    # Add the MCP routes after the HTTP routes so they cannot shadow them, and
    # append them directly instead of mounting: a mount at "/mcp" redirects the
    # bare endpoint to "/mcp/" before the MCP handshake can reject the request.
    app.router.routes.extend(mcp_app.routes)
    # The SPA is the last resort: every API, MCP, documentation and health path
    # is already claimed, and `serve_spa` refuses the reserved ones explicitly.
    # A relative `ui_dir` is read against the project root, so the server finds
    # the bundle regardless of the directory uvicorn was started from.
    ui_dir = Path(settings.api.ui_dir).expanduser()
    if not ui_dir.is_absolute():
        ui_dir = find_config_dir() / ui_dir
    serve_spa(
        app,
        directory=ui_dir,
        reserved=(prefix, MCP_PATH, settings.api.health_path, *DOCS_PATHS),
    )
    get_logger("etlalchemy.api").debug(
        "api.app.created",
        api_prefix=prefix,
        ui_dir=str(ui_dir),
        mcp_path=MCP_PATH,
        contexts=[context.name for context in mcp_server.contexts],
    )
    return app
