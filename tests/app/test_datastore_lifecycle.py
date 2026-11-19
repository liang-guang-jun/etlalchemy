"""Guards the datastore shutdown behaviour of the container.

A context that shares the global datastore must not dispose the engine: every
context used to own a ``_datastore_lifecycle`` resource built from the same
``providers.Selector`` branch, so one engine was closed once per context. It
worked because ``AsyncEngine.dispose()`` is idempotent, which is exactly the kind
of accident this test pins down.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from etlalchemy.app.bootstrap import Container, run_container
from etlalchemy.app.bootstrap.contexts import CONTEXT_SPECS
from etlalchemy.app.bootstrap.factories import SHARED_SCOPE


class _CountingCloser:
    """Records how often ``close`` was awaited."""

    def __init__(self) -> None:
        self.calls = 0

    async def close(self) -> None:
        """Counts the call."""
        self.calls += 1


async def test_a_shared_datastore_is_closed_once(
    config_dir: Path,
    write_config: Callable[[str], None],
    container: Container,
) -> None:
    """Every context defaults to the global datastore, which closes exactly once."""
    write_config(f"database:\n  backend: sqlite\n  sqlite_path: {config_dir.parent / 'shared.db'}\n")
    counter = _CountingCloser()
    real_close = container.global_datastore().close

    async def counting_close() -> None:
        await counter.close()
        await real_close()

    assert container.global_datastore() is container.catalog_datastore()
    container.global_datastore().close = counting_close  # type: ignore[method-assign]
    try:
        async with run_container(container):
            pass
    finally:
        container.global_datastore().close = real_close  # type: ignore[method-assign]

    assert counter.calls == 1


async def test_every_context_shares_the_datastore_by_default(
    config_dir: Path,
    write_config: Callable[[str], None],
    container: Container,
) -> None:
    """The premise of the test above: no context overrides the database."""
    write_config(f"database:\n  backend: sqlite\n  sqlite_path: {config_dir.parent / 'shared.db'}\n")

    for spec in CONTEXT_SPECS:
        datastore = getattr(container, f"{spec.name}_datastore")()
        assert datastore is container.global_datastore(), spec.name


async def test_a_shared_context_keeps_the_engine_open() -> None:
    """A context that reuses the global engine does not close it."""
    from etlalchemy.app.bootstrap.factories import context_datastore_lifecycle

    counter = _CountingCloser()
    resource = context_datastore_lifecycle(counter, SHARED_SCOPE)  # type: ignore[arg-type]
    try:
        assert await anext(resource) is None
    finally:
        await resource.aclose()

    assert counter.calls == 0


async def test_a_dedicated_context_closes_its_engine() -> None:
    """A context with its own database owns the shutdown of that engine."""
    from etlalchemy.app.bootstrap.factories import context_datastore_lifecycle

    counter = _CountingCloser()
    resource = context_datastore_lifecycle(counter, "dedicated")  # type: ignore[arg-type]
    try:
        assert await anext(resource) is None
    finally:
        await resource.aclose()

    assert counter.calls == 1
