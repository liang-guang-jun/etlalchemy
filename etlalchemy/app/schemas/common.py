"""Response models shared by every bounded context."""

from __future__ import annotations

from pydantic import BaseModel


class OkResponse(BaseModel):
    """Result of a command that returns no identifier."""

    ok: bool = True
    """True when the command was applied."""
