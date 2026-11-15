"""Agent runtime: LangChain + LangGraph over the ETLAlchemy MCP endpoint."""

from __future__ import annotations

from etlalchemy.agent.checkpoint import CheckpointSettings, open_checkpointer
from etlalchemy.agent.errors import (
    AgentError,
    AgentTimeoutError,
    ApprovalError,
    LlmProviderError,
    McpConnectionError,
    McpToolError,
    ToolBudgetExceededError,
    UnknownToolError,
    parse_tool_error,
)
from etlalchemy.agent.factory import AgentFactory
from etlalchemy.agent.mcp.client import McpClient
from etlalchemy.agent.mcp.prompts import RENDER_PROMPT_TOOL, build_prompt_catalogue
from etlalchemy.agent.mcp.resources import (
    READ_RESOURCE_TOOL,
    ResourceReader,
    build_catalogue,
)
from etlalchemy.agent.mcp.tools import (
    ToolAnnotations,
    ToolExecutor,
    annotations_of,
    args_hash,
    build_args_model,
    to_langchain_tool,
)
from etlalchemy.agent.observability.mlflow import MlflowSettings, trace_run
from etlalchemy.agent.results import (
    AgentRun,
    ApprovalRequest,
    RunObserver,
    ToolCall,
)
from etlalchemy.agent.runtime import (
    AgentRunner,
    ChatModelFactory,
    ConversationPort,
    RunRequest,
)
from etlalchemy.agent.security.approval import ApprovalDecision, resume_command
from etlalchemy.agent.security.policy import ApprovalPolicy, ToolPolicy
from etlalchemy.agent.service.streaming import RunStream, SseEvent
from etlalchemy.agent.settings import (
    AgentLimits,
    AgentRuntimeSettings,
    ApprovalRule,
)

__all__ = [
    "READ_RESOURCE_TOOL",
    "RENDER_PROMPT_TOOL",
    "AgentError",
    "AgentFactory",
    "AgentLimits",
    "AgentRun",
    "AgentRunner",
    "AgentRuntimeSettings",
    "AgentTimeoutError",
    "ApprovalDecision",
    "ApprovalError",
    "ApprovalPolicy",
    "ApprovalRequest",
    "ApprovalRule",
    "ChatModelFactory",
    "CheckpointSettings",
    "ConversationPort",
    "LlmProviderError",
    "McpClient",
    "McpConnectionError",
    "McpToolError",
    "MlflowSettings",
    "ResourceReader",
    "RunObserver",
    "RunRequest",
    "RunStream",
    "SseEvent",
    "ToolAnnotations",
    "ToolBudgetExceededError",
    "ToolCall",
    "ToolExecutor",
    "ToolPolicy",
    "UnknownToolError",
    "annotations_of",
    "args_hash",
    "build_args_model",
    "build_catalogue",
    "build_prompt_catalogue",
    "open_checkpointer",
    "parse_tool_error",
    "resume_command",
    "to_langchain_tool",
    "trace_run",
]
