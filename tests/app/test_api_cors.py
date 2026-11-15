"""Tests for the configurable CORS middleware of the HTTP API."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from etlalchemy.app.api.app import create_app

ORIGIN = "http://localhost:5173"
"""Origin of the Vite development server used by the tests."""


def test_cors_is_disabled_without_configured_origins(config_dir: Any) -> None:
    """The middleware is not installed when no origin is configured."""
    with TestClient(create_app()) as client:
        response = client.get("/catalog/catalogs", headers={"Origin": ORIGIN})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_cors_answers_a_preflight_for_a_configured_origin(
    config_dir: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured origin gets its preflight answered before any route runs."""
    monkeypatch.setenv("ETLALCHEMY_API__CORS_ORIGINS", f'["{ORIGIN}"]')

    with TestClient(create_app()) as client:
        response = client.options(
            "/catalog/catalogs",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "GET" in response.headers["access-control-allow-methods"]


def test_cors_rejects_an_unconfigured_origin(
    config_dir: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An origin that is not configured gets no allow-origin header."""
    monkeypatch.setenv("ETLALCHEMY_API__CORS_ORIGINS", f'["{ORIGIN}"]')

    with TestClient(create_app()) as client:
        response = client.get(
            "/catalog/catalogs",
            headers={"Origin": "http://evil.example.com"},
        )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
