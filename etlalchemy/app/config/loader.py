"""Loads the layered YAML configuration of the assembly layer."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

from etlalchemy.app.config.settings import AppSettings

CONFIG_FILES_ENV = "ETLALCHEMY_CONFIG_FILES"
"""Environment variable that exports :option:`--config` files to reloaded workers."""

DOTENV_FILE = ".env"
"""Local environment file read from the configuration directory, when present."""


class ConfigError(RuntimeError):
    """Raised when the configuration cannot be read or validated."""


def find_config_dir() -> Path:
    """Returns the directory that holds the configuration files."""
    configured = os.getenv("ETLALCHEMY_CONFIG_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    here = Path(__file__).resolve().parent
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return Path.cwd()


def load_dotenv_file(config_dir: Path) -> bool:
    """Exports ``.env`` from the configuration directory into the environment.

    The values are loaded with ``override=False``, so a variable that is already
    set in the process wins over the file. Because the secrets of the YAML files
    are references such as ``env:DEEPSEEK_API_KEY`` resolved against
    ``os.environ`` at call time, the file has to be read before anything else
    looks a secret up.

    Args:
        config_dir: Directory the configuration files are read from.

    Returns:
        ``True`` when a ``.env`` file existed and was loaded.
    """
    path = config_dir / DOTENV_FILE
    if not path.is_file():
        return False
    load_dotenv(path, override=False)
    return True


def _load_yaml(path: Path) -> dict[str, Any]:
    """Loads a YAML mapping, expanding ``${VAR}`` references; missing is empty."""
    if not path.is_file():
        return {}
    raw = os.path.expandvars(path.read_text(encoding="utf-8"))
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        msg = f"Configuration file must contain a mapping: {path}"
        raise ConfigError(msg)
    return data


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merges ``overlay`` into ``base`` and returns a new mapping."""
    merged = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def load_settings(
    env: str | None = None,
    config_files: Sequence[str | Path] | None = None,
) -> AppSettings:
    """Loads the layered configuration.

    Precedence (high to low): environment variables, the extra files from
    ``config_files`` or :data:`CONFIG_FILES_ENV` (a later file wins), then
    ``config.<env>.yaml``, ``config.default.yaml`` and, when the default file is
    missing, ``config.example.yaml``. Nested mappings are merged; scalars and
    lists are replaced. ``.env`` in the configuration directory is exported
    first, so its variables behave like environment variables.
    """
    config_dir = find_config_dir()
    load_dotenv_file(config_dir)
    environment = env or os.getenv("ETLALCHEMY_ENV", "dev")
    base = config_dir / "config.default.yaml"
    if not base.is_file():
        base = config_dir / "config.example.yaml"
    merged = _load_yaml(base)
    merged = _deep_merge(merged, _load_yaml(config_dir / f"config.{environment}.yaml"))
    for path in extra_config_files(config_files):
        if not path.is_file():
            msg = f"Configuration file not found: {path}"
            raise ConfigError(msg)
        merged = _deep_merge(merged, _load_yaml(path))
    try:
        return AppSettings(**merged)
    except ValidationError as exc:
        msg = f"Invalid configuration from {config_dir}: {exc}"
        raise ConfigError(msg) from exc


def extra_config_files(
    config_files: Sequence[str | Path] | None = None,
) -> list[Path]:
    """Returns the extra configuration files, in merge order.

    Explicit files win over the ones exported through :data:`CONFIG_FILES_ENV`,
    which uvicorn's reloaded workers read.
    """
    if config_files:
        return [Path(path).expanduser() for path in config_files]
    configured = os.getenv(CONFIG_FILES_ENV, "")
    return [Path(part).expanduser() for part in configured.split(os.pathsep) if part]
