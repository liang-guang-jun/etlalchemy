"""Reads the local Databricks CLI configuration without its secrets.

Only the profile names and the workspace hosts are exposed. Tokens, client
secrets and other credential material stay in the file and are resolved by the
Databricks SDK when a client is built.
"""

from __future__ import annotations

import configparser
import os
from pathlib import Path

from etlalchemy.ingestion.ports.data_source import SourceProfile

CONFIG_FILE_ENV = "DATABRICKS_CONFIG_FILE"
"""Environment variable that overrides the location of the CLI configuration."""

DEFAULT_CONFIG_FILE = "~/.databrickscfg"
"""Location the Databricks SDK reads when no override is set."""

SETTINGS_SECTION = "__settings__"
"""Reserved section the CLI stores its own metadata in."""


def config_file() -> Path:
    """Returns the Databricks CLI configuration file of the current process."""
    configured = os.environ.get(CONFIG_FILE_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(DEFAULT_CONFIG_FILE).expanduser()


def read_profiles(path: Path | None = None) -> list[SourceProfile]:
    """Returns the profiles of the local Databricks CLI without their secrets.

    Args:
        path: Configuration file to read; defaults to :func:`config_file`.

    Returns:
        One entry per profile section, in the order the file stores them. A
        missing, unreadable or malformed file yields an empty list.
    """
    parser = configparser.ConfigParser(interpolation=None)
    try:
        if not parser.read(path or config_file(), encoding="utf-8"):
            return []
    except (OSError, UnicodeError, configparser.Error):
        return []
    profiles: list[SourceProfile] = []
    for section in parser.sections():
        if section == SETTINGS_SECTION:
            continue
        host = parser.get(section, "host", fallback="").strip()
        profiles.append(SourceProfile(name=section, host=host or None))
    return profiles
