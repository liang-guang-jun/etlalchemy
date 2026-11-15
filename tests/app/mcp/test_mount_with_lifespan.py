"""Tests that the MCP server is mounted on the HTTP app with a combined lifespan."""

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from etlalchemy.app.api.app import MCP_PATH, create_app

WAIT_TIMEOUT = 10.0


def wait_for(predicate: Callable[[], Any], timeout: float = WAIT_TIMEOUT) -> None:
    """Polls ``predicate`` until it returns a truthy value."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("timed out waiting for the projection")


async def test_mcp_is_mounted_below_its_path(config_dir: Path) -> None:
    """The MCP endpoint rejects a bare HTTP request instead of answering 404."""
    with TestClient(create_app(), follow_redirects=False) as client:
        response = client.post(
            MCP_PATH,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )

        assert response.status_code != 404
        assert 400 <= response.status_code < 500


async def test_unknown_paths_still_answer_404(config_dir: Path) -> None:
    """The MCP routes do not turn into a catch-all."""
    with TestClient(create_app(), follow_redirects=False) as client:
        assert client.get("/unknown").status_code == 404


async def test_http_routes_still_answer_next_to_the_mcp_mount(config_dir: Path) -> None:
    """Mounting the MCP app does not shadow the catalog routes."""
    with TestClient(create_app()) as client:
        assert client.get("/api/catalog/catalogs").status_code == 200
        created = client.post("/api/catalog/catalogs", params={"name": "analytics"})
        assert created.status_code == 200


async def test_combined_lifespan_keeps_the_projection_running(config_dir: Path) -> None:
    """Both lifespans run: the container is wired and the projection advances."""
    with TestClient(create_app()) as client:
        catalog_id = client.post("/api/catalog/catalogs", params={"name": "analytics"}).json()[
            "catalog_id"
        ]

        wait_for(lambda: client.get(f"/api/catalog/catalogs/{catalog_id}").status_code == 200)
        assert client.get(f"/api/catalog/catalogs/{catalog_id}").json()["name"] == "analytics"
