"""Prompt discovery and rendering for the agent.

Server-side MCP prompts are English workflow templates that point at resource
URIs; the agent exposes them through one generic tool and injects their names and
descriptions into its system prompt.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from langchain_core.tools import BaseTool, StructuredTool
from langgraph.errors import GraphBubbleUp
from mcp.types import GetPromptResult, Prompt
from pydantic import BaseModel, Field

RENDER_PROMPT_TOOL = "render_mcp_prompt"
"""Name of the generic prompt tool exposed to the model."""


class PromptArguments(BaseModel):
    """Arguments of the generic prompt tool."""

    name: str = Field(..., description="Name of the server-side prompt.")
    arguments: dict[str, str] | None = Field(
        default=None,
        description="Prompt arguments; omit a prompt argument it does not declare.",
    )


def build_prompt_tool(
    get_prompt: Callable[[str, Mapping[str, str] | None], Awaitable[GetPromptResult]],
) -> BaseTool:
    """Builds the generic ``render_mcp_prompt`` tool."""

    async def invoke(name: str, arguments: dict[str, str] | None = None) -> str:
        try:
            result = await get_prompt(name, arguments)
        except GraphBubbleUp:
            raise
        except Exception as exc:
            # Returned, not raised: the graph would abort on the exception, while
            # the model can read this text and pick another prompt or explain.
            detail = str(exc).strip() or type(exc).__name__
            return f"[internal] cannot render prompt {name!r}: {detail}"
        parts: list[str] = []
        for message in result.messages or []:
            content = message.content
            text = getattr(content, "text", None)
            if isinstance(text, str):
                parts.append(text)
        return "\n\n".join(parts)

    return StructuredTool.from_function(
        coroutine=invoke,
        name=RENDER_PROMPT_TOOL,
        description=(
            "Render a server-side MCP prompt. Use it when the user asks for a known "
            "workflow instead of the generic tools."
        ),
        args_schema=PromptArguments,
    )


def build_prompt_catalogue(prompts: list[Prompt]) -> str:
    """Renders the prompt catalogue injected into the system prompt.

    Args:
        prompts: Prompts advertised by the MCP server.

    Returns:
        One line per prompt, with its required arguments.
    """
    lines: list[str] = []
    for prompt in prompts:
        arguments = ", ".join(argument.name for argument in prompt.arguments or [])
        suffix = f" (args: {arguments})" if arguments else ""
        description = (prompt.description or "").strip()
        lines.append(f"- {prompt.name}{suffix}  {description}".rstrip())
    return "\n".join(lines)
