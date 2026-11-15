"""Container lifecycle shared by every delivery layer.

The FastAPI lifespan and the standalone MCP dev server start and stop the
container the same way; :func:`run_container` is the single place that knows the
order (wire, start the async resources, create the read models, start the
applications, run, stop the applications, shut the resources down, unwire).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from etlalchemy.app.bootstrap.container import Container
from etlalchemy.catalog.application import CatalogApplication
from etlalchemy.catalog.projection.view import CatalogView
from etlalchemy.comment.application import CommentApplication
from etlalchemy.comment.projection.view import CommentView
from etlalchemy.conversation.application import ConversationApplication
from etlalchemy.conversation.projection.view import ConversationView
from etlalchemy.iam.application import IamApplication
from etlalchemy.iam.projection.view import IamView
from etlalchemy.ingestion.application import IngestionApplication
from etlalchemy.ingestion.projection.view import IngestionView
from etlalchemy.llm_config.application import LlmConfigApplication
from etlalchemy.llm_config.projection.view import LlmProviderView
from etlalchemy.semantic.application import ModelApplication
from etlalchemy.semantic.projection.view import SemanticView
from etlalchemy.shared.logging import configure_logging, get_logger
from etlalchemy.vocabulary.application import VocabularyApplication
from etlalchemy.vocabulary.projection.view import VocabularyView

CONTEXTS: tuple[str, ...] = (
    "catalog",
    "iam",
    "ingestion",
    "semantic",
    "vocabulary",
    "comment",
    "llm_config",
    "conversation",
)
"""Bounded contexts whose read models and applications the lifecycle manages."""

Application = (
    CatalogApplication
    | IamApplication
    | IngestionApplication
    | ModelApplication
    | VocabularyApplication
    | CommentApplication
    | LlmConfigApplication
    | ConversationApplication
)
"""Application classes the lifecycle starts and closes."""

View = (
    CatalogView
    | IamView
    | IngestionView
    | SemanticView
    | VocabularyView
    | CommentView
    | LlmProviderView
    | ConversationView
)
"""Read models the lifecycle creates once their datastore is running."""


async def _await_if_needed(result: Awaitable[None] | None) -> None:
    """Awaits a dependency-injector hook that is asynchronous only when needed."""
    if result is not None:
        await result


async def _bootstrap_llm_provider(container: Container) -> None:
    """Ensures the configuration-file LLM provider exists.

    Args:
        container: The started container whose LLM provider context is running.
    """
    llm = container.settings().agent.llm
    if llm is None:
        return
    application = container.llm_config_application()
    await application.ensure_public_provider(
        name=llm.name,
        kind=llm.kind,
        endpoint=llm.endpoint,
        credential_ref=llm.credential_ref,
        token=llm.token,
        default_model=llm.default_model,
        options=llm.options,
    )


@asynccontextmanager
async def run_container(container: Container) -> AsyncIterator[Container]:
    """Wires the container, starts its resources, read models and applications.

    Shared by the FastAPI lifespan and the standalone MCP dev server, so both
    start the container exactly the same way.

    Args:
        container: The container to wire, start and later shut down.

    Yields:
        The same container, while its applications and resources are running.
    """
    configure_logging(container.settings().logging)
    log = get_logger("etlalchemy.lifecycle")
    log.info("lifecycle.start", contexts=list(CONTEXTS))
    container.wire(modules=container.wiring_config.modules)
    try:
        await _await_if_needed(container.init_resources())
        for context in CONTEXTS:
            view: View = getattr(container, f"{context}_view")()
            await view.create_table()
            application: Application = getattr(container, f"{context}_application")()
            await application.start()
            log.debug("lifecycle.read_model.ready", context=context)
        await _bootstrap_llm_provider(container)
        log.info("lifecycle.resources.started")
        yield container
    finally:
        log.info("lifecycle.stop")
        for context in CONTEXTS:
            closing: Application = getattr(container, f"{context}_application")()
            await closing.aclose()
        await _await_if_needed(container.shutdown_resources())
        container.unwire()
        log.info("lifecycle.stopped")


@asynccontextmanager
async def api_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan that runs the container for the HTTP application.

    Args:
        app: The HTTP application whose ``container`` attribute is started.

    Yields:
        Nothing; the request handlers run while the container is alive.
    """
    container: Any = app.container  # type: ignore[attr-defined]
    async with run_container(container):
        yield
