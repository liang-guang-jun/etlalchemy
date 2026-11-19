"""Tests for the bearer authentication wiring of the assembly layer."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from dependency_injector import providers
from etlalchemy.app.auth import SessionAuthenticator
from etlalchemy.app.bootstrap import Container


async def test_session_authenticator_shares_the_iam_application(
    config_dir: Path,
    container: Container,
) -> None:
    """The authenticator validates through the container's IAM application."""
    authenticator = container.session_authenticator()

    assert isinstance(authenticator, SessionAuthenticator)
    assert container.session_authenticator() is authenticator
    session_id = uuid4()
    assert authenticator.extract_session_id(authenticator.format_token(session_id)) == session_id


async def test_mcp_session_resolver_can_be_overridden(
    config_dir: Path,
    container: Container,
) -> None:
    """Tests replace the resolver so tools receive a caller without a transport."""
    session_id = uuid4()
    container.mcp_session_resolver.override(providers.Object(session_id))

    assert container.mcp_session_resolver() == session_id

    container.mcp_session_resolver.reset_override()
