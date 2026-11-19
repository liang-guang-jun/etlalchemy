"""Guards the package boundaries the architecture depends on.

The rules live in ``.github/copilot-instructions.md`` and `docs/concepts/
architecture.md`, but until now nothing failed when one of them was broken.
Each test scans the source text, so it catches an import that only exists to
make a shortcut work.
"""

from __future__ import annotations

import pathlib
import re

import pytest

SOURCE_ROOT = pathlib.Path("etlalchemy")

CONTEXTS = (
    "catalog",
    "comment",
    "conversation",
    "iam",
    "ingestion",
    "llm_config",
    "semantic",
    "vocabulary",
)
"""Every bounded context package."""

ASSEMBLY = "etlalchemy.app"
"""The assembly layer that contexts must never import."""

_BROADCAST = re.compile(r"^(?:import|from)\s+\S+", re.MULTILINE)


def _modules(*roots: str) -> list[pathlib.Path]:
    """Returns every Python module under the given package roots."""
    paths: list[pathlib.Path] = []
    for root in roots:
        paths.extend(SOURCE_ROOT.joinpath(*root.split("/")).rglob("*.py"))
    return paths


def _imports(path: pathlib.Path) -> set[str]:
    """Returns the modules a file imports, resolved from its import statements."""
    imported: set[str] = set()
    for match in _BROADCAST.finditer(path.read_text(encoding="utf-8")):
        statement = match.group(0)
        if statement.startswith("from "):
            imported.add(statement.split()[1])
        else:
            imported.add(statement.split()[1].split(".")[0])
    return imported


def _offenders(paths: list[pathlib.Path], predicate: str) -> list[str]:
    """Returns the files that import a module matching ``predicate``."""
    pattern = re.compile(predicate)
    return sorted(str(path) for path in paths if any(map(pattern.match, _imports(path))))


@pytest.mark.parametrize("context", CONTEXTS)
def test_a_context_never_imports_the_assembly_layer(context: str) -> None:
    """A context must stay unaware of FastAPI, the container and the config."""
    offenders = _offenders(_modules(context), rf"{re.escape(ASSEMBLY)}(\.|$)")

    assert offenders == []


def test_the_shared_layer_imports_only_its_allowed_toolkit() -> None:
    """``shared/`` may use the stdlib, eventsourcing, structlog and pydantic only."""
    forbidden = (
        r"etlalchemy\.app(\.|$)",
        r"etlalchemy\.(?:catalog|comment|conversation|iam|ingestion|llm_config"
        r"|semantic|vocabulary)(\.|$)",
        r"fastapi(\.|$)",
        r"fastmcp(\.|$)",
        r"dependency_injector(\.|$)",
        r"sqlalchemy(\.|$)",
    )

    offenders = [path for pattern in forbidden for path in _offenders(_modules("shared"), pattern)]

    assert offenders == []


def test_the_config_layer_never_imports_a_context() -> None:
    """Settings describe a context; they must not depend on one.

    ``app/config/settings.py`` used to import ``DEFAULT_TARGET_TYPES`` from the
    comment context and ``PROFILE_KINDS`` from the LLM provider context, which
    made the assembly layer depend on business rules.
    """
    pattern = (
        r"etlalchemy\.(?:catalog|comment|conversation|iam|ingestion|llm_config"
        r"|semantic|vocabulary)(\.|$)"
    )

    assert _offenders(_modules("app/config"), pattern) == []


def test_the_agent_package_never_imports_the_assembly_layer() -> None:
    """The agent runtime stays transport agnostic and container free."""
    assert _offenders(_modules("agent"), rf"{re.escape(ASSEMBLY)}(\.|$)") == []


def test_the_agent_package_never_imports_fastmcp() -> None:
    """FastMCP belongs to the delivery layer, not to the runtime."""
    assert _offenders(_modules("agent"), r"fastmcp(\.|$)") == []


def test_only_the_read_model_implementations_import_sqlalchemy() -> None:
    """A context touches SQLAlchemy through its view, never in its use cases."""
    allowed = re.compile(
        r"etlalchemy/(?:"
        + "|".join(CONTEXTS)
        + r")/projection/(?:sqlalchemy|tables)\.py$"
    )
    offenders = [
        str(path)
        for path in _modules(*CONTEXTS)
        if any(map(re.compile(r"sqlalchemy(\.|$)").match, _imports(path)))
        and not allowed.match(path.as_posix())
    ]

    assert sorted(offenders) == []


def test_views_never_import_sqlalchemy() -> None:
    """The read-model interface and the projection stay backend agnostic."""
    views = [path for path in _modules(*CONTEXTS) if path.name == "view.py"]

    assert _offenders(views, r"sqlalchemy(\.|$)") == []


def test_the_projection_modules_never_import_sqlalchemy() -> None:
    """``projection.py`` wires events to the view; only the view talks SQL."""
    modules = [path for path in _modules(*CONTEXTS) if path.name == "projection.py"]

    assert _offenders(modules, r"sqlalchemy(\.|$)") == []


def test_the_assembly_layer_never_imports_sqlalchemy() -> None:
    """Infrastructure construction belongs in the factories, not in ``app/``."""
    assert _offenders(_modules("app"), r"sqlalchemy(\.|$)") == []


def test_a_context_only_reaches_another_context_explicitly() -> None:
    """Cross-context imports stay limited to the documented seams.

    The assembly layer may use any context. Inside ``etlalchemy/`` a context
    reaches a sibling only through an application, a read model or a port, and
    those edges are listed here so a new one is a deliberate edit.
    """
    allowed = {
        # ingestion orchestrates catalog use cases and reads its view.
        "ingestion": {"catalog"},
        # vocabulary and semantic resolve catalog objects on their links.
        "vocabulary": {"catalog"},
        "semantic": {"catalog"},
        # comment resolves targets through five read models and authorizes via IAM.
        "comment": {"catalog", "semantic", "vocabulary", "ingestion", "iam"},
        # conversation and llm_config authorize through an IAM port.
        "conversation": {"iam"},
        "llm_config": {"iam"},
        # catalog and iam are leaves.
        "catalog": set(),
        "iam": set(),
    }

    offenders: dict[str, set[str]] = {}
    for context, permitted in allowed.items():
        pattern = re.compile(
            r"etlalchemy\.(" + "|".join(CONTEXTS) + r")(?:\.|$)"
        )
        for path in _modules(context):
            for module in _imports(path):
                match = pattern.match(module)
                if match is None or match.group(1) == context:
                    continue
                if match.group(1) not in permitted:
                    offenders.setdefault(context, set()).add(f"{path} -> {module}")

    assert offenders == {}


def test_the_context_list_matches_the_packages_on_disk() -> None:
    """The guard above is only useful while it names every context."""
    packages = {
        path.name
        for path in SOURCE_ROOT.iterdir()
        if path.is_dir() and (path / "application.py").is_file()
    }

    assert packages == set(CONTEXTS)
