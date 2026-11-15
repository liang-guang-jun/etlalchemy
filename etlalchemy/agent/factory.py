"""Builds a runnable agent from its ports."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any
from uuid import UUID

from etlalchemy.agent.mcp.client import HttpConnector, McpClient, McpConnector
from etlalchemy.agent.runtime import AgentRunner, ChatModelFactory, ConversationPort
from etlalchemy.agent.settings import AgentRuntimeSettings

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

ConnectorFactory = Callable[[Mapping[str, str], UUID | None], McpConnector]
"""Builds the MCP connector of one caller.

The first argument is the HTTP header set (normally the bearer token), the
second the IAM session id. An HTTP connector only needs the headers, while an
in-process connector — which runs inside the already authenticated request —
needs the session id instead.
"""


class AgentFactory:
    """Builds an :class:`~etlalchemy.agent.runtime.AgentRunner`.

    The factory holds no request state: one instance serves every run, and each
    run builds its own tools because they close over the run identity and the
    observer.
    """

    def __init__(
        self,
        *,
        settings: AgentRuntimeSettings,
        conversation: ConversationPort,
        chat_model_factory: ChatModelFactory,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        client: McpClient | None = None,
        connector_factory: ConnectorFactory | None = None,
    ) -> None:
        """Stores the ports the runner is built from.

        Args:
            settings: Runtime limits and policy.
            conversation: Conversation store the runs write to.
            chat_model_factory: Resolves the chat model of a provider.
            checkpointer: Durable saver, or ``None`` to keep runs in memory only.
            client: Pre-built MCP client, or ``None`` to build one per call.
            connector_factory: Builds the connector of a caller; defaults to
                streamable HTTP against ``settings.mcp_url``.
        """
        self._settings = settings
        self._conversation = conversation
        self._chat_model_factory = chat_model_factory
        self._checkpointer = checkpointer
        self._client = client
        self._connector_factory = connector_factory

    def for_caller(
        self,
        *,
        headers: Mapping[str, str],
        session_id: UUID | None = None,
    ) -> AgentRunner:
        """Builds a runner whose MCP client acts as one caller.

        Args:
            headers: HTTP headers, normally the caller's bearer token.
            session_id: IAM session of the caller; the in-process connector
                needs it, an HTTP connector ignores it.

        Returns:
            A runner bound to a fresh MCP client.
        """
        client = self._client
        if client is None:
            connector = (
                self._connector_factory(headers, session_id)
                if self._connector_factory is not None
                else HttpConnector(self._settings.mcp_url, headers=headers)
            )
            client = McpClient(
                connector,
                request_timeout_seconds=self._settings.request_timeout_seconds,
                connect_retries=self._settings.connect_retries,
            )
        return AgentRunner(
            client=client,
            settings=self._settings,
            conversation=self._conversation,
            chat_model_factory=self._chat_model_factory,
            checkpointer=self._checkpointer,
        )
