"""MCP server that exposes every bounded context as tools, resources and prompts.

Each context package registers itself with
:func:`etlalchemy.app.mcp.registry.mcp_context`; this module only mounts the
resulting sub-servers and never names a context.

Behaviour of ``FastMCP.mount()`` observed with fastmcp 4.1.6 through an in-memory
``fastmcp.Client``, which decides the shape of this module:

* Mounting without ``namespace`` keeps every name a client sees: the tool
  ``create_catalog``, the resource ``catalog:///all``, the template
  ``catalog:///{catalog_id}`` and the prompt ``import-catalog-workflow`` survive
  the mount unchanged, and calls are forwarded to the mounted server.
* Mounting with ``namespace="catalog"`` rewrites all of them
  (``catalog_create_catalog``, ``catalog://catalog//all`` - the doubled slash
  comes from the empty authority of a ``scheme:///path`` URI - and
  ``catalog_import-catalog-workflow``), which would break every existing client,
  so the namespace is omitted until two contexts really collide on a name.
* Only the parent's ``instructions`` reach the client; a mounted server's
  instructions are dropped instead of merged, so the summary below is composed
  from the context packages here.
* A mounted server's lifespan runs for every client session of the parent, so
  mounting changes neither when the container starts nor when it stops.
* ``auth`` is a property of the parent's HTTP application, not of the mounted
  components: ``MCPServer`` passes the verifier to the parent only, and every
  request to ``/mcp`` — including a call of a tool that lives on a mounted
  sub-server — is authenticated before the request reaches any provider.
  ``tests/app/mcp/test_mcp_auth.py`` proves it by calling a mounted tool without
  a token (401, no write) and with one (the tool runs). A sub-server therefore
  has ``auth is None``, which is safe because only the parent's ``http_app`` is
  served; never expose a child's own application.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from fastmcp.server.server import LifespanCallable

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.mcp import (  # registration entry point, do not remove
    catalog,
    comment,
    conversation,
    iam,
    ingestion,
    llm_config,
    semantic,
    vocabulary,
)
from etlalchemy.app.mcp.auth import IamTokenVerifier
from etlalchemy.app.mcp.logging import McpCallLoggingMiddleware
from etlalchemy.app.mcp.registry import build_contexts

INSTRUCTIONS = " ".join(
    (
        catalog.INSTRUCTIONS,
        comment.INSTRUCTIONS,
        conversation.INSTRUCTIONS,
        iam.INSTRUCTIONS,
        ingestion.INSTRUCTIONS,
        llm_config.INSTRUCTIONS,
        semantic.INSTRUCTIONS,
        vocabulary.INSTRUCTIONS,
        "Tools report conflicts and unknown references with a bracketed prefix.",
    )
)
"""Instructions advertised to MCP clients."""


class MCPServer:
    """Mounts one FastMCP sub-server per registered context."""

    name = "etlalchemy"
    """Name advertised to MCP clients."""

    def __init__(
        self,
        container: Container,
        lifespan: LifespanCallable[Any] | None = None,
        *,
        require_auth: bool | None = None,
    ) -> None:
        """Builds the server and mounts every registered context.

        ``lifespan`` is only needed when the server runs on its own (see
        :mod:`etlalchemy.app.mcp.dev`); the HTTP application combines this server
        with the API lifespan instead. ``require_auth`` overrides
        ``mcp.require_auth`` for tests that drive the in-memory transport.
        """
        self.container: Container = container
        self.require_auth: bool = (
            container.settings().mcp.require_auth if require_auth is None else require_auth
        )
        verifier: IamTokenVerifier | None = None
        if self.require_auth:
            verifier = IamTokenVerifier(container.session_authenticator())
        self.mcp: FastMCP = FastMCP(
            self.name,
            instructions=INSTRUCTIONS,
            lifespan=lifespan,
            auth=verifier,
        )
        self.mcp.add_middleware(McpCallLoggingMiddleware())
        self.contexts: list[FastMCP] = build_contexts(container)
        for context in self.contexts:
            self.mcp.mount(context)
