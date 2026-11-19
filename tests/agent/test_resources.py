"""Tests of the MCP resource reader."""

from __future__ import annotations

from uuid import uuid4

from etlalchemy.agent.mcp.resources import READ_RESOURCE_TOOL, ResourceReader, normalise_uri
from etlalchemy.agent.settings import AgentRuntimeSettings

from tests.agent.support import FakeMcpClient, FakeObserver


class RecordingClient(FakeMcpClient):
    """Fake client that remembers the URIs it was asked to read."""

    def __init__(self) -> None:
        """Starts with an empty list of requested URIs."""
        super().__init__()
        self.uris: list[str] = []

    async def read_resource(self, uri: str) -> object:
        """Records the URI and answers like the base fake."""
        self.uris.append(uri)
        return await super().read_resource(uri)


async def test_a_read_is_traced_like_a_tool_call() -> None:
    """The model reads resources with a tool, so the chat must show that call."""
    client = FakeMcpClient()
    observer = FakeObserver()
    reader = ResourceReader(
        client.read_resource,
        AgentRuntimeSettings(),
        observer=observer,
        run_id=uuid4(),
    )

    text = await reader.read("catalog:///all")

    assert text == '{"ok": true}'
    kinds = [kind for kind, _ in observer.events]
    assert kinds == ["tool.started", "resource.read", "tool.finished"]
    assert observer.events[0][1]["tool"] == READ_RESOURCE_TOOL
    assert observer.events[2][1]["status"] == "ok"


async def test_a_failed_read_answers_the_model_instead_of_raising() -> None:
    """A broken read is a tool result: the graph must not abort on it."""

    async def broken(uri: str) -> object:
        raise RuntimeError(uri)

    observer = FakeObserver()
    reader = ResourceReader(
        broken,
        AgentRuntimeSettings(),
        observer=observer,
        run_id=uuid4(),
    )

    text = await reader.read("catalog:///nope")

    assert text.startswith("[internal] cannot read resource ")
    kinds = [kind for kind, _ in observer.events]
    assert kinds == ["tool.started", "tool.finished"]
    assert observer.events[1][1]["status"] == "error"


async def test_a_failed_read_reports_the_reason() -> None:
    """The model must learn why a read failed, or it repeats the same URI."""

    async def missing(uri: str) -> object:
        msg = f"Resource not found: {uri!r}"
        raise RuntimeError(msg)

    reader = ResourceReader(missing, AgentRuntimeSettings())

    text = await reader.read("catalog:///nope")

    assert "Resource not found" in text


def test_a_network_uri_keeps_its_authority() -> None:
    """Only the resource schemes are rewritten; https keeps its host."""
    assert normalise_uri("https://example.com/a/b") == "https://example.com/a/b"


async def test_a_uri_missing_the_third_slash_still_reads() -> None:
    """A model that drops a slash asks for the scheme:///path form anyway."""
    client = RecordingClient()
    reader = ResourceReader(client.read_resource, AgentRuntimeSettings())

    text = await reader.read("catalog://edd16b7e-5c44-422d-a029-e307248c2e61/schemas")

    assert text == '{"ok": true}'
    assert client.uris == ["catalog:///edd16b7e-5c44-422d-a029-e307248c2e61/schemas"]
