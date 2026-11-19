"""Tests that the vocabulary use cases emit structured logs."""

from __future__ import annotations

from uuid import UUID

import pytest
from etlalchemy.shared.logging import reset_logging
from etlalchemy.vocabulary.aggregates.errors import UnknownLinkError, UnknownTermError
from etlalchemy.vocabulary.application import VocabularyApplication
from structlog.testing import capture_logs


@pytest.fixture(autouse=True)
def _fresh_loggers() -> None:
    """Drops cached loggers so ``capture_logs`` sees the application output."""
    reset_logging()


async def test_create_domain_logs_start_and_done(
    vocabulary_app: VocabularyApplication,
) -> None:
    """The create use case logs the command name and the new id."""
    with capture_logs() as logs:
        domain_id = await vocabulary_app.create_domain("finance")

    assert [entry["event"] for entry in logs] == [
        "vocabulary.domain.create start",
        "vocabulary.domain.create done",
    ]
    assert logs[0]["name"] == "finance"
    assert logs[1]["domain_id"] == str(domain_id)


async def test_term_change_logs_the_command_and_the_nested_reads(
    vocabulary_app: VocabularyApplication,
) -> None:
    """A write logs its own start/done around the debug logs of the reads it makes."""
    domain_id = await vocabulary_app.create_domain("finance")
    await vocabulary_app.create_term(domain_id, "invoice", "A bill")

    with capture_logs() as logs:
        await vocabulary_app.change_term_definition(
            domain_id,
            "invoice",
            "A bill to a customer",
        )

    events = [entry["event"] for entry in logs]
    assert events[0] == "vocabulary.term.definition.change start"
    assert "vocabulary.term.get start" in events
    assert events[-1] == "vocabulary.term.definition.change done"


async def test_rename_logs_both_paths_and_the_descendant_count(
    vocabulary_app: VocabularyApplication,
) -> None:
    """The rename log carries the old path, the new path and the subtree size."""
    domain_id = await vocabulary_app.create_domain("finance")
    await vocabulary_app.create_term(domain_id, "Revenue", "Recognized revenue")
    await vocabulary_app.create_term(
        domain_id,
        "ARR",
        "Annual recurring revenue",
        parent="Revenue",
    )

    with capture_logs() as logs:
        await vocabulary_app.rename_term(domain_id, "Revenue", "Sales")

    done = next(entry for entry in logs if entry["event"] == "vocabulary.term.rename done")
    assert done["old_path"] == "Revenue"
    assert done["new_path"] == "Sales"
    assert done["descendants"] == 1


async def test_link_logs_the_target_payload(
    vocabulary_app: VocabularyApplication,
) -> None:
    """The link logs carry the target kind and field name."""
    domain_id = await vocabulary_app.create_domain("finance")
    await vocabulary_app.create_term(domain_id, "invoice", "A bill")
    target_id = "00000000-0000-0000-0000-000000000001"

    with capture_logs() as logs, pytest.raises(UnknownLinkError, match="does not exist"):
        await vocabulary_app.link_term(
            domain_id,
            "invoice",
            UUID(target_id),
            "catalog",
        )

    start = next(entry for entry in logs if entry["event"] == "vocabulary.term.link start")
    assert start["target_id"] == target_id
    assert start["target_kind"] == "catalog"


async def test_unknown_term_is_logged_before_raising(
    vocabulary_app: VocabularyApplication,
) -> None:
    """The lookup helper logs at debug level and then raises."""
    domain_id = await vocabulary_app.create_domain("finance")

    with capture_logs() as logs, pytest.raises(UnknownTermError):
        await vocabulary_app.get_term(domain_id, "missing")

    assert "vocabulary.term.not_found" in [entry["event"] for entry in logs]
