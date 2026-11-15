"""Serving the built single-page application from the HTTP API.

The SPA lives in ``dist/ui`` and is uploaded next to the Python code when the
service runs as a Databricks App, so one process answers both the static files
and ``/api``. Registering the catch-all last keeps the API, the MCP server, the
OpenAPI document and the health endpoint authoritative: only a path none of them
claims can reach the history fallback.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, Response
from starlette.routing import Route

INDEX_FILE = "index.html"
"""Document the history fallback answers with."""

HTML_MEDIA_TYPE = "text/html"
"""Media type a browser navigation asks for."""

IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
"""Cache header of the content-hashed assets Vite writes into ``assets/``."""

NO_CACHE = "no-cache"
"""Cache header of ``index.html``, which names the current asset hashes."""


def serve_spa(
    app: FastAPI,
    *,
    directory: Path,
    reserved: Sequence[str],
) -> bool:
    """Serves the built SPA with a history fallback.

    Args:
        app: The HTTP application to add the catch-all route to. It must be
            called after every other route is registered.
        directory: Directory of the production bundle, normally ``dist/ui``.
        reserved: Paths the fallback must not answer, such as the API prefix and
            the MCP endpoint; a path below one of them stays a 404.

    Returns:
        ``True`` when the bundle holds an ``index.html`` and the route was
        added, ``False`` when the server runs without a user interface.
    """
    root = directory.expanduser().resolve()
    index = root / INDEX_FILE
    if not index.is_file():
        return False
    # The fallback must never answer for an API or MCP path, so a missing route
    # keeps failing with the JSON 404 the clients already understand.
    guarded = tuple(path for path in reserved if path)

    async def spa(request: Request) -> Response:
        """Answers a built asset or the single-page entry point.

        Args:
            request: Incoming request, read for its path and ``Accept`` header.

        Returns:
            The requested file, or ``index.html`` for a browser navigation.

        Raises:
            HTTPException: 404 for a reserved path, a missing asset that is not
                a navigation, or a path that escapes the bundle.
        """
        full_path = str(request.path_params.get("full_path", ""))
        if _is_reserved(full_path, guarded):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
        asset = _resolve(root, full_path)
        if asset is not None and asset.is_file():
            return FileResponse(asset, headers=_cache_header(full_path))
        if HTML_MEDIA_TYPE not in request.headers.get("accept", ""):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
        return FileResponse(index, media_type=HTML_MEDIA_TYPE, headers={"Cache-Control": NO_CACHE})

    app.router.routes.append(
        Route(
            "/{full_path:path}",
            spa,
            methods=["GET", "HEAD"],
            include_in_schema=False,
        ),
    )
    return True


def _is_reserved(full_path: str, reserved: Sequence[str]) -> bool:
    """Returns whether a request path belongs to the API, MCP or documentation.

    Args:
        full_path: Request path below the site root.
        reserved: Absolute paths and path prefixes the fallback must skip.

    Returns:
        ``True`` when the path equals a reserved entry or starts with one.
    """
    path = f"/{full_path}"
    return any(path == entry or path.startswith(f"{entry}/") for entry in reserved)


def _resolve(root: Path, full_path: str) -> Path | None:
    """Resolves a request path inside the bundle.

    Args:
        root: Resolved bundle directory.
        full_path: Request path below the site root.

    Returns:
        The file the path names, or ``None`` when it is empty or escapes the
        bundle.
    """
    if not full_path:
        return None
    candidate = (root / full_path).resolve()
    return candidate if candidate.is_relative_to(root) else None


def _cache_header(full_path: str) -> dict[str, str]:
    """Returns the cache header of a built asset.

    Args:
        full_path: Request path below the site root.

    Returns:
        A long-lived cache header for the content-hashed ``assets/`` tree, and
        ``no-cache`` for everything else.
    """
    return {"Cache-Control": IMMUTABLE_CACHE if full_path.startswith("assets/") else NO_CACHE}
