"""Assembly entry points: settings, container and lifecycle in one place."""

from etlalchemy.app.bootstrap.container import Container
from etlalchemy.app.bootstrap.lifecycle import CONTEXTS, api_lifespan, run_container
from etlalchemy.app.bootstrap.settings import load_app_settings

__all__ = [
    "CONTEXTS",
    "Container",
    "api_lifespan",
    "load_app_settings",
    "run_container",
]
