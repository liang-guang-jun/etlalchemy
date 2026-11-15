"""Uvicorn entry point of the ETLAlchemy HTTP API."""

from __future__ import annotations

from etlalchemy.app.api.app import create_app
from etlalchemy.app.bootstrap import load_app_settings
from etlalchemy.shared.logging import configure_logging

_settings = load_app_settings()
"""Settings resolved once, for the uvicorn worker and for the reloader child."""

# Configure logging before the application is built. ``uvicorn --reload`` runs a
# fresh process that imports this module, and with ``log_config=None`` uvicorn's
# own startup records only reach the root handler once it exists.
configure_logging(_settings.logging)

app = create_app()


def main() -> None:
    """Runs the HTTP API with uvicorn using the configured host and port."""
    import uvicorn

    uvicorn.run(
        "etlalchemy.app.main:app",
        host=_settings.api.host,
        port=_settings.api.port,
        reload=_settings.api.debug,
        log_config=None,
    )


if __name__ == "__main__":
    main()
