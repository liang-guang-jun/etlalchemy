"""Settings of the agent runtime.

The runtime never reads the assembly layer's pydantic settings: the container
builds these plain value objects from ``AppSettings.agent`` so the package stays
importable without FastAPI, dependency-injector or pydantic-settings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from etlalchemy.agent.redaction import DEFAULT_REDACT_KEYS

ApprovalAction = Literal["auto", "require_approval", "deny"]


@dataclass(frozen=True)
class ApprovalRule:
    """One tool approval rule."""

    match: str = "*"
    """Glob pattern matched against the tool name."""
    when: dict[str, str] = field(default_factory=dict)
    """Conditions that must all hold, for example ``{"tenant_env": "prod"}``."""
    action: ApprovalAction = "require_approval"
    """Decision the rule produces when it matches."""


@dataclass(frozen=True)
class AgentLimits:
    """Hard limits of one agent run."""

    max_tool_calls: int = 25
    """Maximum number of tool calls of one run."""
    max_wall_clock_seconds: int = 600
    """Maximum duration of one run."""
    tool_timeout_seconds: int = 60
    """Timeout of a single tool call."""
    max_tool_output_chars: int = 32_000
    """Maximum length of one tool result before it is truncated."""
    max_tool_args_chars: int = 2_000
    """Maximum length of the argument preview sent to the browser."""
    max_tool_result_preview_chars: int = 4_000
    """Maximum length of the result preview sent to the browser."""
    max_reasoning_chars: int = 16_000
    """Maximum length of the thinking kept with a message."""
    token_budget: int = 128_000
    """Token budget of one run."""


@dataclass(frozen=True)
class AgentRuntimeSettings:
    """Everything the runtime needs, independently of the configuration format."""

    mcp_url: str = "http://127.0.0.1:8000/mcp"
    """Streamable HTTP endpoint of the MCP server; used when no connector is
    configured."""
    transport: Literal["in_process", "http"] = "in_process"
    """How the agent reaches the MCP server.

    ``in_process`` reuses the server object of this process, ``http`` calls
    :attr:`mcp_url` like any other client.
    """
    request_timeout_seconds: float = 30.0
    """Timeout of one MCP request that is not a tool call."""
    connect_retries: int = 3
    """Number of connection attempts before ``McpConnectionError`` is raised."""
    history_limit: int = 20
    """Number of previous messages replayed into a run."""
    limits: AgentLimits = field(default_factory=AgentLimits)
    """Hard limits applied to every run."""
    allowlist: frozenset[str] | None = None
    """When set, only these tool names are exposed."""
    denylist: frozenset[str] = frozenset()
    """Tool names that are never exposed, applied after ``allowlist``."""
    redact_argument_keys: frozenset[str] = frozenset(DEFAULT_REDACT_KEYS)
    """Argument names masked in the preview that reaches the browser."""
    approval_default: str = "deny"
    """Decision used when no rule matches a destructive tool."""
    approval_rules: tuple[ApprovalRule, ...] = ()
    """Rules evaluated in order; the first match wins."""
    system_prompt: str = ""
    """Extra instructions appended to the generated system prompt."""

    def exposes(self, tool_name: str) -> bool:
        """Returns whether a tool name survives the allow and deny lists.

        Args:
            tool_name: Name advertised by the MCP server.

        Returns:
            ``True`` when the tool may be exposed to the model.
        """
        if tool_name in self.denylist:
            return False
        return self.allowlist is None or tool_name in self.allowlist
