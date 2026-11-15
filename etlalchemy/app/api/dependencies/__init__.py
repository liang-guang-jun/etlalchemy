"""FastAPI dependencies shared by the route modules."""

from __future__ import annotations

from etlalchemy.app.api.dependencies.auth import get_auth_session, get_session_id, oauth2_scheme

__all__ = ["get_auth_session", "get_session_id", "oauth2_scheme"]
