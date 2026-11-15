"""Value objects and enumerations of the conversation context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

MessageRole = Literal["user", "assistant", "tool", "system"]
"""Role of one message inside a conversation."""

ConversationStatus = Literal["OPEN", "DISCARDED"]
"""Lifecycle status of a conversation; ``DISCARDED`` is terminal."""

RunStatus = Literal["running", "completed", "failed", "interrupted"]
"""Lifecycle status of one agent run."""

ApprovalStatus = Literal["pending", "approved", "denied"]
"""State of one human-in-the-loop approval."""

MAX_TITLE_LENGTH = 200
"""Maximum length of a conversation title."""

MAX_TOOL_NAME_LENGTH = 200
"""Maximum length of a tool name kept in a trace record."""


@dataclass(frozen=True)
class ResourceAccess:
    """One MCP resource read during an agent run."""

    uri: str
    """URI of the resource that was read."""
    size_bytes: int = 0
    """Size of the returned payload in bytes."""
    mime_type: str = ""
    """MIME type of the returned payload."""
    at: datetime | None = None
    """Moment the resource was read, or ``None``."""


@dataclass(frozen=True)
class ToolCallRecord:
    """One MCP tool call made during an agent run."""

    tool: str
    """Name of the tool that was called."""
    args_hash: str = ""
    """Stable digest of the arguments, kept for provenance."""
    status: str = "ok"
    """Outcome of the call, for example ``ok``, ``error`` or ``denied``."""
    duration_ms: int = 0
    """Wall-clock duration of the call in milliseconds."""
    error_code: str | None = None
    """Bracketed error category the tool reported, or ``None``."""
    args_json: str = ""
    """Redacted, truncated JSON of the arguments shown in the tool drawer."""
    result_preview: str = ""
    """Truncated text the tool returned, shown in the tool drawer."""


@dataclass(frozen=True)
class TokenUsage:
    """Token accounting of one assistant message."""

    input_tokens: int = 0
    """Prompt tokens billed by the provider."""
    output_tokens: int = 0
    """Completion tokens billed by the provider."""

    @property
    def total_tokens(self) -> int:
        """Returns the sum of prompt and completion tokens."""
        return self.input_tokens + self.output_tokens


def normalise_title(title: str | None) -> str:
    """Returns the title without surrounding whitespace, or an empty string."""
    return "" if title is None else title.strip()


def clamp_content(content: str, max_chars: int) -> str:
    """Returns the content, truncated and marked when it exceeds the limit."""
    if max_chars <= 0 or len(content) <= max_chars:
        return content
    marker = "…(truncated)"
    return content[: max(0, max_chars - len(marker))] + marker
