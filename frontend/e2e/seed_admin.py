"""Seeds the first system administrator for the end-to-end tests.

The production CLI reads the password from a hidden TTY prompt, which cannot be
driven from a test runner. This script calls the same application use case
directly, so the seeded account is created exactly like ``etla iam bootstrap
admin`` would create it.

Usage (from the repository root, with the backend running):

    uv run python frontend/e2e/seed_admin.py --email e2e@example.com

The password comes from ``SEED_ADMIN_PASSWORD`` and defaults to ``Passw0rd!``.
"""

from __future__ import annotations

import argparse
import asyncio
import os

from etlalchemy.app.bootstrap import Container

DEFAULT_PASSWORD = "Passw0rd!"
"""Password used when ``SEED_ADMIN_PASSWORD`` is not set."""


async def seed(email: str, password: str) -> None:
    """Creates the first system administrator.

    Args:
        email: Login and email address of the administrator.
        password: Password of the new administrator.
    """
    container = Container()
    await container.init_resources()
    application = container.iam_application()
    await application.start()
    try:
        if await application.bootstrap_status():
            print("bootstrap already completed")
            return
        await application.bootstrap_admin(email, password)
        print(f"admin seeded: {email}")
    finally:
        await application.aclose()
        await container.shutdown_resources()
        container.unwire()


def main() -> None:
    """Parses the arguments and runs the seeding coroutine."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Email of the administrator.")
    arguments = parser.parse_args()
    password = os.environ.get("SEED_ADMIN_PASSWORD", DEFAULT_PASSWORD)
    asyncio.run(seed(arguments.email, password))


if __name__ == "__main__":
    main()
