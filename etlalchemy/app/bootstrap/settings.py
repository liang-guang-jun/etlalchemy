"""Single entry point for loading the layered application settings."""

from __future__ import annotations

from etlalchemy.app.config.loader import load_settings
from etlalchemy.app.config.settings import AppSettings


def load_app_settings() -> AppSettings:
    """Loads the layered settings from YAML files and environment variables.

    The CLI server and the uvicorn entry point both call this, so a reloaded
    worker reads the same configuration as the process that started it.

    Returns:
        The resolved application settings.
    """
    return load_settings()
