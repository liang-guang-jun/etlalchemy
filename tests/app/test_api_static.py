"""Tests for serving the built single-page application from the HTTP API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from etlalchemy.app.api.app import create_app

INDEX = "<!doctype html><title>etlalchemy</title>"
"""Minimal document standing in for the Vite build."""

BUNDLE = "console.log('bundle');"
"""Minimal content-hashed asset standing in for the Vite build."""


@pytest.fixture
def ui_dir(tmp_path: Path) -> Path:
    """Writes a minimal production bundle and returns its directory."""
    directory = tmp_path / "ui"
    (directory / "assets").mkdir(parents=True)
    (directory / "index.html").write_text(INDEX, encoding="utf-8")
    (directory / "assets" / "index.js").write_text(BUNDLE, encoding="utf-8")
    return directory


def test_root_serves_the_index(
    config_dir: Any,
    ui_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A browser navigation to the site root gets the single-page document."""
    monkeypatch.setenv("ETLALCHEMY_API__UI_DIR", str(ui_dir))

    with TestClient(create_app()) as client:
        response = client.get("/", headers={"Accept": "text/html"})

    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["cache-control"] == "no-cache"


def test_client_route_falls_back_to_the_index(
    config_dir: Any,
    ui_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reloading a client-side route answers the SPA instead of a 404."""
    monkeypatch.setenv("ETLALCHEMY_API__UI_DIR", str(ui_dir))

    with TestClient(create_app()) as client:
        response = client.get("/iam/users", headers={"Accept": "text/html"})

    assert response.status_code == 200
    assert response.text == INDEX


def test_built_asset_is_served_with_a_long_cache(
    config_dir: Any,
    ui_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A content-hashed asset is served verbatim and cached immutably."""
    monkeypatch.setenv("ETLALCHEMY_API__UI_DIR", str(ui_dir))

    with TestClient(create_app()) as client:
        response = client.get("/assets/index.js")

    assert response.status_code == 200
    assert response.text == BUNDLE
    assert "immutable" in response.headers["cache-control"]


def test_api_paths_are_not_swallowed_by_the_fallback(
    config_dir: Any,
    ui_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown API path stays a JSON 404 even for a document request."""
    monkeypatch.setenv("ETLALCHEMY_API__UI_DIR", str(ui_dir))

    with TestClient(create_app()) as client:
        response = client.get("/api/missing", headers={"Accept": "text/html"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_missing_asset_without_html_accept_is_a_404(
    config_dir: Any,
    ui_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a navigation falls back; an XHR for a missing file stays a 404."""
    monkeypatch.setenv("ETLALCHEMY_API__UI_DIR", str(ui_dir))

    with TestClient(create_app()) as client:
        response = client.get("/assets/missing.js", headers={"Accept": "application/javascript"})

    assert response.status_code == 404


def test_server_without_a_bundle_answers_only_the_api(config_dir: Any) -> None:
    """An unbuilt frontend is not an error: the fallback is simply absent."""
    with TestClient(create_app()) as client:
        assert client.get("/", headers={"Accept": "text/html"}).status_code == 404
        assert client.get("/api/catalog/catalogs").status_code == 200
