"""Errors raised by the agent runtime."""

from __future__ import annotations


class AgentError(Exception):
    """Base class of every agent error; the original failure is chained."""


class McpConnectionError(AgentError):
    """Raised when the MCP endpoint cannot be reached or initialised."""


class McpToolError(AgentError):
    """Raised when a tool answers with an error; carries the bracketed category."""

    def __init__(self, message: str, *, code: str = "[internal]") -> None:
        """Stores the message and the bracketed category the tool reported."""
        super().__init__(message)
        self.code = code


class UnknownToolError(AgentError):
    """Raised when a tool name does not resolve to an exposed tool."""


class ApprovalError(AgentError):
    """Raised when an approval cannot be requested or resumed."""


class ToolBudgetExceededError(AgentError):
    """Raised when a run exceeds its tool budget."""


class TokenBudgetExceededError(AgentError):
    """Raised when a run exceeds its token budget."""


class AgentTimeoutError(AgentError):
    """Raised when a run exceeds its wall-clock budget."""


class LlmProviderError(AgentError):
    """Raised when no LLM provider is available or one cannot be built."""


def parse_tool_error(message: str) -> tuple[str, str]:
    """Splits a bracketed tool error into its category and the remaining text.

    Args:
        message: Tool output, for example ``[not_found] table 1 does not exist``.

    Returns:
        The category (``[not_found]`` by default) and the message without it.
    """
    text = message.strip()
    if text.startswith("[") and "]" in text:
        head, _, rest = text.partition("]")
        return f"{head}]", rest.strip()
    return "[internal]", text
