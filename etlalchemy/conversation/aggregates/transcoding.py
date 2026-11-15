"""Transcodings that keep the conversation value objects JSON-safe.

Events carry whole value objects (never ``None`` in their place), so the default
``JSONTranscoder`` needs one registered transcoding per nested dataclass.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from eventsourcing.persistence import JSONTranscoder, Transcoding

from etlalchemy.conversation.aggregates.types import (
    ResourceAccess,
    TokenUsage,
    ToolCallRecord,
)


def _encode_datetime(value: datetime | None) -> str | None:
    """Encodes an optional datetime as ISO text."""
    return None if value is None else value.isoformat()


def _decode_datetime(value: str | None) -> datetime | None:
    """Decodes ISO text back into an optional datetime."""
    return None if value is None else datetime.fromisoformat(value)


class ResourceAccessAsDict(Transcoding):
    """Transcoding that stores a :class:`ResourceAccess` as a mapping."""

    type = ResourceAccess
    name = "etlalchemy_conversation_resource_access"

    def encode(self, obj: Any) -> dict[str, Any]:
        """Encodes a resource access record."""
        access: ResourceAccess = obj
        return {
            "uri": access.uri,
            "size_bytes": access.size_bytes,
            "mime_type": access.mime_type,
            "at": _encode_datetime(access.at),
        }

    def decode(self, data: Any) -> ResourceAccess:
        """Decodes a resource access record."""
        return ResourceAccess(
            uri=str(data["uri"]),
            size_bytes=int(data.get("size_bytes", 0)),
            mime_type=str(data.get("mime_type", "")),
            at=_decode_datetime(data.get("at")),
        )


class ToolCallRecordAsDict(Transcoding):
    """Transcoding that stores a :class:`ToolCallRecord` as a mapping."""

    type = ToolCallRecord
    name = "etlalchemy_conversation_tool_call"

    def encode(self, obj: Any) -> dict[str, Any]:
        """Encodes a tool call record."""
        record: ToolCallRecord = obj
        return {
            "tool": record.tool,
            "args_hash": record.args_hash,
            "status": record.status,
            "duration_ms": record.duration_ms,
            "error_code": record.error_code,
            "args_json": record.args_json,
            "result_preview": record.result_preview,
        }

    def decode(self, data: Any) -> ToolCallRecord:
        """Decodes a tool call record."""
        return ToolCallRecord(
            tool=str(data["tool"]),
            args_hash=str(data.get("args_hash", "")),
            status=str(data.get("status", "ok")),
            duration_ms=int(data.get("duration_ms", 0)),
            error_code=data.get("error_code"),
            args_json=str(data.get("args_json", "")),
            result_preview=str(data.get("result_preview", "")),
        )


class TokenUsageAsDict(Transcoding):
    """Transcoding that stores a :class:`TokenUsage` as a mapping."""

    type = TokenUsage
    name = "etlalchemy_conversation_token_usage"

    def encode(self, obj: Any) -> dict[str, Any]:
        """Encodes a token usage record."""
        usage: TokenUsage = obj
        return {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        }

    def decode(self, data: Any) -> TokenUsage:
        """Decodes a token usage record."""
        return TokenUsage(
            input_tokens=int(data.get("input_tokens", 0)),
            output_tokens=int(data.get("output_tokens", 0)),
        )


def register_conversation_transcodings(transcoder: JSONTranscoder) -> None:
    """Registers every conversation value object transcoding.

    Args:
        transcoder: The transcoder the application configures.
    """
    transcoder.register(ResourceAccessAsDict())
    transcoder.register(ToolCallRecordAsDict())
    transcoder.register(TokenUsageAsDict())
