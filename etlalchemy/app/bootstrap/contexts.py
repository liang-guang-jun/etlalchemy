"""Registry of the bounded contexts the process assembles.

Every context is described once, here. The container, the lifecycle, the HTTP
application and the table-naming test all read this list, so adding a context is
one entry instead of an edit in ten modules.

A context that needs more than the common wiring (an IAM port, a target lookup,
extra options) keeps those providers in :mod:`etlalchemy.app.bootstrap.container`;
the spec only describes what every context has.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi import APIRouter

    from etlalchemy.app.bootstrap.factories import ViewFactory

__all__ = ["CONTEXT_SPECS", "ContextSpec", "context_spec", "request_contexts"]


@dataclass(frozen=True)
class ContextSpec:
    """Everything the assembly layer needs to know about one bounded context."""

    name: str
    """Context name; also the settings attribute and the provider prefix."""

    view_factory: ViewFactory
    """Builds the read model and hosts the projection resource."""

    application: type[Any]
    """Application class the lifecycle starts and closes."""

    router: APIRouter | None = None
    """HTTP router included under the API prefix."""

    error_handlers: Callable[[Any], None] | None = None
    """Registers the context's exception handlers on the application."""

    @property
    def view_provider(self) -> str:
        """Name of the container provider that holds the read model."""
        return f"{self.name}_view"

    @property
    def application_provider(self) -> str:
        """Name of the container provider that holds the application service."""
        return f"{self.name}_application"

    @property
    def projection_provider(self) -> str:
        """Name of the container provider that runs the projection."""
        return f"{self.name}_projection_runner"


def _load_routes() -> dict[str, tuple[Any, Any]]:
    """Imports the HTTP router and the error installer of every context.

    The imports are deferred so importing this module never loads FastAPI unless
    the assembly layer actually builds an HTTP application.
    """
    from etlalchemy.app.api.routes import (
        catalog,
        comment,
        iam,
        ingestion,
        semantic,
        vocabulary,
    )

    contexts = {
        "catalog": catalog,
        "comment": comment,
        "iam": iam,
        "ingestion": ingestion,
        "semantic": semantic,
        "vocabulary": vocabulary,
    }
    return {
        name: (module.router, module.add_exception_handlers) for name, module in contexts.items()
    }


def _build_specs() -> tuple[ContextSpec, ...]:
    """Builds the spec of every context in assembly order.

    Only the view factories and application classes are imported here; the HTTP
    routers are resolved by :func:`request_contexts` on first use, because the
    route modules import the container, which imports this module.
    """
    from etlalchemy.app.bootstrap.factories import (
        CatalogViewFactory,
        CommentViewFactory,
        ConversationViewFactory,
        IamViewFactory,
        IngestionViewFactory,
        LlmConfigViewFactory,
        SemanticViewFactory,
        VocabularyViewFactory,
    )
    from etlalchemy.catalog.application import CatalogApplication
    from etlalchemy.comment.application import CommentApplication
    from etlalchemy.conversation.application import ConversationApplication
    from etlalchemy.iam.application import IamApplication
    from etlalchemy.ingestion.application import IngestionApplication
    from etlalchemy.llm_config.application import LlmConfigApplication
    from etlalchemy.semantic.application import ModelApplication
    from etlalchemy.vocabulary.application import VocabularyApplication

    definitions: tuple[tuple[str, ViewFactory, type[Any]], ...] = (
        ("catalog", CatalogViewFactory(), CatalogApplication),
        ("iam", IamViewFactory(), IamApplication),
        ("ingestion", IngestionViewFactory(), IngestionApplication),
        ("semantic", SemanticViewFactory(), ModelApplication),
        ("vocabulary", VocabularyViewFactory(), VocabularyApplication),
        ("comment", CommentViewFactory(), CommentApplication),
        ("llm_config", LlmConfigViewFactory(), LlmConfigApplication),
        ("conversation", ConversationViewFactory(), ConversationApplication),
    )
    return tuple(
        ContextSpec(name=name, view_factory=view_factory, application=application)
        for name, view_factory, application in definitions
    )


CONTEXT_SPECS: tuple[ContextSpec, ...] = _build_specs()
"""The bounded contexts, in the order the lifecycle starts them."""


def request_contexts() -> tuple[ContextSpec, ...]:
    """Returns the specs that serve HTTP, with their router and error mapping.

    The route modules import the container and the container imports this
    module, so they cannot be imported while it is being defined; the delivery
    layer calls this once the application is being created.

    Returns:
        The HTTP-facing specs, in registry order.
    """
    routes = _load_routes()
    resolved: list[ContextSpec] = []
    for spec in CONTEXT_SPECS:
        router, handlers = routes.get(spec.name, (None, None))
        if router is None:
            continue
        resolved.append(replace(spec, router=router, error_handlers=handlers))
    return tuple(resolved)


def context_spec(name: str) -> ContextSpec:
    """Returns the spec of one context.

    Args:
        name: Context name, for example ``catalog``.

    Returns:
        The registered spec.

    Raises:
        KeyError: If no context carries that name.
    """
    for spec in CONTEXT_SPECS:
        if spec.name == name:
            return spec
    msg = f"unknown bounded context {name!r}"
    raise KeyError(msg)
