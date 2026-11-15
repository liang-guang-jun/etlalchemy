"""Tests of the MCP client session reuse."""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any

import pytest

from etlalchemy.agent.mcp.client import HttpConnector, McpClient, build_http_client


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> tuple[McpClient, list[int]]:
    """Returns a client whose connection is counted instead of opened."""
    instance = McpClient(HttpConnector("http://example.invalid/mcp"))
    opens = [0]

    async def fake_open() -> tuple[AsyncExitStack, Any]:
        opens[0] += 1
        return AsyncExitStack(), object()

    monkeypatch.setattr(instance, "_open", fake_open)
    return instance, opens


async def test_lifespan_reuses_one_connection(
    client: tuple[McpClient, list[int]],
) -> None:
    """Every session inside the lifespan uses the same MCP connection."""
    instance, opens = client
    async with instance.lifespan():
        async with instance.session():
            pass
        async with instance.session():
            pass
    assert opens == [1]


async def test_sessions_outside_a_lifespan_are_independent(
    client: tuple[McpClient, list[int]],
) -> None:
    """Without a lifespan each block opens its own connection."""
    instance, opens = client
    async with instance.session():
        pass
    async with instance.session():
        pass
    assert opens == [2]


async def test_the_runner_opens_one_session_per_run(client: tuple[McpClient, list[int]]) -> None:
    """A run enters the lifespan exactly once."""
    from langchain_core.messages import AIMessage

    from etlalchemy.agent.runtime import AgentRunner, RunRequest
    from etlalchemy.agent.settings import AgentRuntimeSettings
    from tests.agent.support import FakeConversation, FakeMcpClient, RecordingModel
    from uuid import uuid4

    transport = FakeMcpClient()

    async def chat_model_factory(*_: object) -> object:
        return RecordingModel(messages=iter([AIMessage(content="a"), AIMessage(content="b")]))

    runner = AgentRunner(
        client=transport,  # type: ignore[arg-type]
        settings=AgentRuntimeSettings(),
        conversation=FakeConversation(),
        chat_model_factory=chat_model_factory,  # type: ignore[arg-type]
        checkpointer=None,
    )
    for _ in range(2):
        await runner.run(
            RunRequest(
                conversation_id=uuid4(),
                session_id=uuid4(),
                user_id=uuid4(),
                tenant_id=None,
                content="hello",
            ),
        )

    assert transport.lifespans == 2


def test_the_mcp_connection_ignores_ambient_proxies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The internal MCP call never travels through a configured proxy.

    ``ALL_PROXY``/``HTTP_PROXY`` are exported by many container images, and the
    endpoint is this process's own server: honouring them sends an internal
    request to a proxy that cannot reach it. The client therefore sets
    ``trust_env=False``.
    """
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:9")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)

    client = build_http_client(
        headers={"Authorization": "Bearer token"},
        timeout_seconds=5.0,
    )

    assert client.trust_env is False
    assert client.headers["authorization"] == "Bearer token"
