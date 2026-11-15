"""Resource access and the resource catalogue the model can see.

The catalogue is injected into the system prompt, so the model knows which URIs
exist without spending a turn listing them. Reads go through one generic tool
rather than one tool per resource, which keeps the tool surface stable when a new
bounded context adds resources.
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from uuid import UUID

from langchain_core.tools import BaseTool, StructuredTool
from langgraph.errors import GraphBubbleUp
from mcp.types import ReadResourceResult, Resource, ResourceTemplate
from pydantic import BaseModel, Field

from etlalchemy.agent.mcp.tools import args_hash, truncate
from etlalchemy.agent.redaction import preview_json, preview_text
from etlalchemy.agent.results import RunObserver, ToolCall
from etlalchemy.agent.settings import AgentRuntimeSettings
from etlalchemy.conversation.aggregates.types import ResourceAccess
from etlalchemy.shared.logging import get_logger

READ_RESOURCE_TOOL = "read_mcp_resource"
"""Name of the generic resource tool exposed to the model."""

TWO_SLASH_URI = re.compile(r"^(?P<scheme>[a-z][a-z0-9+.\-]*)://(?!/)(?P<rest>.*)$")
"""Matches a resource URI written with two slashes, which parses as an authority."""

NETWORK_SCHEMES = frozenset({"http", "https"})
"""Schemes whose ``//authority`` form is meaningful, so it is never rewritten."""


def normalise_uri(uri: str) -> str:
    """Rewrites ``scheme://path`` into the ``scheme:///path`` a resource uses.

    A model that echoes a template such as ``catalog:///{catalog_id}/schemas``
    sometimes drops one slash. ``catalog://<id>/schemas`` then parses as scheme
    plus authority, which matches no template, so the server answers "resource
    not found" even though the object exists. Every resource of this server
    lives below an empty authority, so the missing slash is restored.

    Args:
        uri: URI the model asked for, already stripped of surrounding blanks.

    Returns:
        The URI to read: unchanged when it already carries three slashes or uses
        a network scheme such as ``https``.
    """
    text = uri.strip()
    match = TWO_SLASH_URI.match(text)
    if match is None or match.group("scheme") in NETWORK_SCHEMES:
        return text
    return f"{match.group('scheme')}:///{match.group('rest')}"


class ResourceArguments(BaseModel):
    """Arguments of the generic resource tool."""

    uri: str = Field(..., description="Full resource URI, for example catalog:///all.")


class ResourceReader:
    """Reads MCP resources, traces them and forwards them to the observer."""

    def __init__(
        self,
        read_resource: Callable[[str], Awaitable[ReadResourceResult]],
        settings: AgentRuntimeSettings,
        observer: RunObserver | None = None,
        run_id: UUID | None = None,
        accessed: list[ResourceAccess] | None = None,
    ) -> None:
        """Stores the transport, the limits and the trace sink."""
        self._read = read_resource
        self._settings = settings
        self._observer = observer
        self._run_id = run_id
        self._accessed = accessed if accessed is not None else []
        self._log = get_logger("agent.resources")

    @property
    def accessed(self) -> list[ResourceAccess]:
        """Returns every resource read so far, in read order."""
        return self._accessed

    async def read(self, uri: str) -> str:
        """Reads one resource and returns its textual payload.

        The read is traced like any other tool call: the model asked for it through
        ``read_mcp_resource``, so the chat shows a card with the URI it read, how
        long it took and a preview of the payload. Without those events a read only
        reached the sources list, which made it look like nothing ran.

        Args:
            uri: Full resource URI; a missing slash after the scheme is restored.

        Returns:
            The JSON text the server answered with, truncated to the budget, or
            the failure text when the read did not work. A failure is returned
            rather than raised: the graph aborts on an exception, and the model
            is the only actor that can retry with a corrected URI or explain the
            failure to the reader.

        Raises:
            ToolBudgetExceededError: If the run already spent its tool budget.
        """
        requested = uri
        uri = normalise_uri(uri)
        if uri != requested:
            self._log.debug("agent.resource.uri.normalised", requested=requested, uri=uri)
        digest = args_hash({"uri": uri})
        args_json = preview_json({"uri": uri}, self._settings.limits.max_tool_args_chars)
        started = time.perf_counter()
        if self._observer is not None and self._run_id is not None:
            await self._observer.tool_started(
                run_id=self._run_id,
                call=ToolCall(
                    tool=READ_RESOURCE_TOOL,
                    args_hash=digest,
                    status="running",
                    args_json=args_json,
                ),
            )
        try:
            result = await self._read(uri)
        except GraphBubbleUp:
            raise
        except Exception as exc:
            await self._finished(digest, args_json, started, status="error", code="[internal]")
            # The reason is handed to the model: "resource not found" is what
            # tells it that its URI is wrong, while a bare failure looks like a
            # broken server and gets retried unchanged.
            detail = str(exc).strip() or type(exc).__name__
            failed = f"[internal] cannot read resource {uri!r}: {detail}"
            self._log.warning("agent.resource.failed", uri=uri, error=detail)
            return truncate(failed, self._settings.limits.max_tool_output_chars)
        text = _payload_text(result)
        access = ResourceAccess(
            uri=uri,
            size_bytes=len(text.encode("utf-8")),
            mime_type=_mime_type(result),
        )
        self._accessed.append(access)
        self._log.debug("agent.resource.read", uri=uri, size_bytes=access.size_bytes)
        if self._observer is not None and self._run_id is not None:
            await self._observer.resource_read(run_id=self._run_id, access=access)
        await self._finished(digest, args_json, started, status="ok", code=None, text=text)
        return truncate(text, self._settings.limits.max_tool_output_chars)

    async def _finished(
        self,
        digest: str,
        args_json: str,
        started: float,
        *,
        status: str,
        code: str | None,
        text: str = "",
    ) -> None:
        """Forwards the end of a read as a finished tool call."""
        if self._observer is None or self._run_id is None:
            return
        await self._observer.tool_finished(
            run_id=self._run_id,
            call=ToolCall(
                tool=READ_RESOURCE_TOOL,
                args_hash=digest,
                status=status,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error_code=code,
                args_json=args_json,
                result_preview=preview_text(
                    text,
                    self._settings.limits.max_tool_result_preview_chars,
                ),
            ),
        )


def _mime_type(result: ReadResourceResult) -> str:
    """Returns the MIME type of the first content block."""
    for item in result.contents or []:
        mime = getattr(item, "mimeType", None)
        if isinstance(mime, str):
            return mime
    return ""


def _payload_text(result: ReadResourceResult) -> str:
    """Returns the payload of a resource read as text."""
    parts: list[str] = []
    for item in result.contents or []:
        payload = getattr(item, "text", None)
        if isinstance(payload, str):
            parts.append(payload)
            continue
        blob = getattr(item, "blob", None)
        if isinstance(blob, str):
            parts.append(blob)
    return "\n".join(parts)


def build_catalogue(
    resources: list[Resource],
    templates: list[ResourceTemplate],
) -> str:
    """Renders the resource catalogue injected into the system prompt.

    Args:
        resources: Static resources advertised by the MCP server.
        templates: Resource templates advertised by the MCP server.

    Returns:
        A compact, ASCII-only listing grouped by URI scheme.
    """
    lines: list[str] = []
    for resource in resources:
        description = (resource.description or "").strip()
        lines.append(f"- {resource.uri}  {description}".rstrip())
    for template in templates:
        description = (template.description or "").strip()
        lines.append(f"- {template.uri_template}  {description}".rstrip())
    return "\n".join(lines)


def build_resource_tool(reader: ResourceReader) -> BaseTool:
    """Builds the generic ``read_mcp_resource`` tool."""

    async def invoke(uri: str) -> str:
        return await reader.read(uri)

    return StructuredTool.from_function(
        coroutine=invoke,
        name=READ_RESOURCE_TOOL,
        description=(
            "Read an MCP resource by URI, which always looks like scheme:///path "
            "(three slashes). Unknown or malformed ids answer null or [] instead of "
            "failing, so a wrong id is not an error."
        ),
        args_schema=ResourceArguments,
    )
