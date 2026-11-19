"""Tests of the context registry that drives the assembly layer."""

from __future__ import annotations

import pytest

from etlalchemy.app.bootstrap import CONTEXTS, Container
from etlalchemy.app.bootstrap.contexts import (
    CONTEXT_SPECS,
    context_spec,
    request_contexts,
)
from etlalchemy.app.bootstrap.lifecycle import CONTEXTS as LIFECYCLE_CONTEXTS


def test_every_spec_has_the_common_wiring() -> None:
    """Each context names a view factory and an application class."""
    for spec in CONTEXT_SPECS:
        assert spec.name
        assert spec.view_factory is not None
        assert spec.application.__name__.endswith("Application")


def test_the_names_are_unique() -> None:
    """Two contexts cannot share a name; the provider prefixes would collide."""
    names = [spec.name for spec in CONTEXT_SPECS]

    assert len(names) == len(set(names))


def test_the_lifecycle_uses_the_registry_in_order() -> None:
    """The lifecycle starts the contexts in registry order."""
    assert LIFECYCLE_CONTEXTS == tuple(spec.name for spec in CONTEXT_SPECS)


def test_the_bootstrap_reexports_the_same_list() -> None:
    """``CONTEXTS`` is one list, not a second hand-maintained copy."""
    assert CONTEXTS == LIFECYCLE_CONTEXTS


def test_the_container_exposes_a_provider_for_every_spec() -> None:
    """The provider names the lifecycle resolves must exist on the container."""
    for spec in CONTEXT_SPECS:
        assert hasattr(Container, spec.view_provider), spec.view_provider
        assert hasattr(Container, spec.application_provider), spec.application_provider
        assert hasattr(Container, spec.projection_provider), spec.projection_provider


def test_every_http_context_has_a_router_and_an_error_mapping() -> None:
    """A context that serves HTTP must also map its errors, or it answers 500."""
    for spec in request_contexts():
        assert spec.router is not None
        assert spec.error_handlers is not None


def test_the_routerless_contexts_are_the_internal_ones() -> None:
    """Only the contexts with no HTTP surface stay out of the request list."""
    served = {spec.name for spec in request_contexts()}
    internal = {spec.name for spec in CONTEXT_SPECS} - served

    assert internal == {"llm_config", "conversation"}


def test_lookup_by_name_returns_the_same_object() -> None:
    """The helper resolves the registered spec."""
    for spec in CONTEXT_SPECS:
        assert context_spec(spec.name) is spec


def test_lookup_of_an_unknown_name_raises() -> None:
    """A typo fails loudly instead of silently wiring nothing."""
    with pytest.raises(KeyError):
        context_spec("warehouse")


def test_every_context_declares_its_tables_under_its_own_prefix() -> None:
    """Read-model tables follow ``<context>_<plural>`` for the registered names."""
    for spec in CONTEXT_SPECS:
        metadata = spec.view_factory.view_class.view_metadata
        misplaced = [
            name for name in metadata.tables if not name.startswith(f"{spec.name}_")
        ]
        assert misplaced == [], f"{spec.name}: {misplaced}"
