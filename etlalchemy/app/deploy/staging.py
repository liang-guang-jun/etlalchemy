"""Building the folder tree that is uploaded as the Databricks App source.

The platform builds a workspace folder: with a ``pyproject.toml`` and a
``uv.lock`` it runs ``uv sync`` and then the command from ``app.yaml``. The
staged tree therefore carries the package, the prebuilt SPA, the lock file and a
generated ``app.yaml``; the frontend is not built on the platform because the
repository keeps it in ``frontend/`` and the bundle is already reproducible
locally.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from etlalchemy.app.config.loader import CONFIG_FILES_ENV
from etlalchemy.app.deploy.errors import DeployError
from etlalchemy.app.deploy.snapshot import EXCLUDED_DIRECTORIES, EXCLUDED_SUFFIXES

APP_YAML = "app.yaml"
"""Execution configuration the platform reads from the app root."""

BUNDLE_DIRECTORY = "dist/ui"
"""Where the staged SPA lands, matching ``ApiSettings.ui_dir``."""

DEFAULT_CONFIG = "config.default.yaml"
"""Configuration file staged first when the source tree has one."""

METADATA_FILES = ("pyproject.toml", "uv.lock", "README.md", "LICENSE")
"""Files the platform needs to install the project, in this order."""

PACKAGE_DIRECTORY = "etlalchemy"
"""Python package that holds the service."""

PYPROJECT_TAIL = """

[tool.uv]
# The platform build only needs the runtime dependencies; the dev group would
# install the linters and the test suite into the app image.
default-groups = []
"""
"""Section appended to the staged ``pyproject.toml`` when it has no ``[tool.uv]``."""

SECRET_PATTERN = re.compile(
    r"^\s*([A-Za-z0-9_]*(?:cipher_key|password|token|secret|dsn|credential)[A-Za-z0-9_]*)\s*:\s*(.+)$",
    re.IGNORECASE,
)
"""Matches a configuration line that looks like an inline secret."""

REFERENCE_PREFIXES = ("env:", "file:", "profile:")
"""Values that reference a secret instead of embedding one."""


@dataclass(frozen=True, slots=True)
class StagingSpec:
    """Inputs of one staging run."""

    source: Path
    """Repository root the source is read from."""

    ui_dir: Path
    """Directory holding the built SPA."""

    config_files: tuple[Path, ...]
    """Extra configuration files to upload, in merge order."""

    command: tuple[str, ...]
    """Command written into ``app.yaml``."""

    health_timeout_seconds: int
    """Seconds the platform waits for the health endpoint."""

    health_path: str = "/health"
    """Health endpoint the platform probes."""


@dataclass(frozen=True, slots=True)
class StagedSource:
    """Result of a staging run."""

    root: Path
    """Directory holding the tree to upload."""

    config_names: tuple[str, ...]
    """Configuration file names, in the order the app reads them."""

    warnings: tuple[str, ...]
    """Preflight warnings for the operator."""


def build_staging(spec: StagingSpec, target: Path) -> StagedSource:
    """Writes the app source tree into ``target``.

    Args:
        spec: Inputs of the run.
        target: Empty directory the tree is written to.

    Returns:
        The staged tree, the configuration names in read order and the warnings.

    Raises:
        DeployError: When the bundle or a required metadata file is missing, or
            two configuration files share a name.
    """
    _copy_package(spec.source, target)
    _copy_metadata(spec.source, target)
    _copy_bundle(spec.ui_dir, target)
    configs = _select_configs(spec)
    names = _copy_configs(configs, target)
    (target / APP_YAML).write_text(_app_yaml(spec, names), encoding="utf-8")
    warnings = (*_secret_warnings(configs), *_backend_warnings(configs))
    return StagedSource(root=target, config_names=names, warnings=warnings)


def _copy_package(source: Path, target: Path) -> None:
    """Copies the Python package, leaving generated caches behind.

    Args:
        source: Repository root.
        target: Staging directory.

    Raises:
        DeployError: When the package directory is missing.
    """
    package = source / PACKAGE_DIRECTORY
    if not package.is_dir():
        msg = (
            f"the package directory {package} does not exist; "
            "run the command from the repository root"
        )
        raise DeployError(msg)
    shutil.copytree(package, target / PACKAGE_DIRECTORY, ignore=_ignore_generated)


def _copy_metadata(source: Path, target: Path) -> None:
    """Copies the build metadata the platform installs the project from.

    Args:
        source: Repository root.
        target: Staging directory.

    Raises:
        DeployError: When a required file is missing.
    """
    for name in METADATA_FILES:
        path = source / name
        if not path.is_file():
            msg = f"{name} is required by the platform build but is missing from {source}"
            raise DeployError(msg)
        shutil.copy2(path, target / name)
    pyproject = target / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    if "[tool.uv]" not in text:
        pyproject.write_text(f"{text.rstrip()}{PYPROJECT_TAIL}", encoding="utf-8")


def _copy_bundle(ui_dir: Path, target: Path) -> None:
    """Copies the built SPA into the staged tree.

    Args:
        ui_dir: Directory holding the bundle.
        target: Staging directory.

    Raises:
        DeployError: When the directory holds no ``index.html``.
    """
    index = ui_dir / "index.html"
    if not index.is_file():
        msg = (
            f"the frontend bundle is missing in {ui_dir}; build it with "
            "'pnpm --dir frontend build' or drop --no-build"
        )
        raise DeployError(msg)
    shutil.copytree(ui_dir, target / BUNDLE_DIRECTORY)


def _select_configs(spec: StagingSpec) -> list[Path]:
    """Returns the configuration files to upload, in read order.

    Args:
        spec: Inputs of the run.

    Returns:
        ``config.default.yaml`` when the source has one, then the files the
        caller passed.
    """
    configs: list[Path] = []
    default = spec.source / DEFAULT_CONFIG
    if default.is_file():
        configs.append(default)
    configs.extend(spec.config_files)
    return configs


def _copy_configs(configs: Iterable[Path], target: Path) -> tuple[str, ...]:
    """Copies the configuration files next to the app source.

    Args:
        configs: Files to upload, in read order.
        target: Staging directory.

    Returns:
        The file names, in read order.

    Raises:
        DeployError: When a file is missing or two files share a name.
    """
    names: list[str] = []
    for path in configs:
        resolved = path.expanduser()
        if not resolved.is_file():
            msg = f"configuration file not found: {resolved}"
            raise DeployError(msg)
        if resolved.name in names:
            msg = (
                f"two configuration files are named {resolved.name}; "
                "a later file would overwrite an earlier one"
            )
            raise DeployError(msg)
        shutil.copy2(resolved, target / resolved.name)
        names.append(resolved.name)
    return tuple(names)


def _app_yaml(spec: StagingSpec, config_names: tuple[str, ...]) -> str:
    """Renders the ``app.yaml`` of the staged app.

    Args:
        spec: Inputs of the run.
        config_names: Configuration files the app reads, in order.

    Returns:
        The YAML document.
    """
    document: dict[str, Any] = {
        "command": list(spec.command),
        "health_check": {
            "path": spec.health_path,
            "timeout_seconds": spec.health_timeout_seconds,
        },
    }
    if config_names:
        document["env"] = [
            {"name": CONFIG_FILES_ENV, "value": os.pathsep.join(config_names)},
        ]
    return yaml.safe_dump(document, sort_keys=False, default_flow_style=False)


def _secret_warnings(configs: Iterable[Path]) -> tuple[str, ...]:
    """Reports inline secrets that would be readable from the workspace.

    Args:
        configs: Configuration files that are uploaded.

    Returns:
        One warning per suspicious line.
    """
    warnings: list[str] = []
    for path in configs:
        try:
            lines = path.expanduser().read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for number, line in enumerate(lines, start=1):
            match = SECRET_PATTERN.match(line)
            if match is None:
                continue
            key, value = match.group(1), match.group(2).strip().strip("\"'")
            if not value or value.startswith(REFERENCE_PREFIXES):
                continue
            warnings.append(
                f"{path.name}:{number} stores {key} in the workspace; "
                "prefer an env: or profile: reference",
            )
    return tuple(warnings)


def _backend_warnings(configs: Iterable[Path]) -> tuple[str, ...]:
    """Reports a database that loses data when the app restarts.

    Args:
        configs: Configuration files that are uploaded.

    Returns:
        A warning when the merged configuration selects SQLite.
    """
    merged: dict[str, Any] = {}
    for path in configs:
        try:
            data: Any = yaml.safe_load(path.expanduser().read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            continue
        if isinstance(data, dict):
            merged = _merge(merged, data)
    database = merged.get("database")
    backend = database.get("backend") if isinstance(database, dict) else None
    if backend in (None, "sqlite"):
        return (
            "the app resolves the sqlite backend, whose file lives on ephemeral "
            "storage: pass --config with a Postgres or Lakebase DSN to keep the event store",
        )
    return ()


def _merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Merges two configuration mappings the way the loader does.

    Args:
        base: Lower layer.
        overlay: Higher layer.

    Returns:
        A new mapping, with nested dictionaries merged and everything else
        replaced.
    """
    merged = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _merge(existing, value)
        else:
            merged[key] = value
    return merged


def _ignore_generated(directory: str, names: list[str]) -> set[str]:
    """Selects generated files `copytree` leaves out.

    Args:
        directory: Directory being copied; unused, required by the signature.
        names: Entries of that directory.

    Returns:
        The entries to skip.
    """
    del directory
    return {
        name for name in names if name in EXCLUDED_DIRECTORIES or name.endswith(EXCLUDED_SUFFIXES)
    }
