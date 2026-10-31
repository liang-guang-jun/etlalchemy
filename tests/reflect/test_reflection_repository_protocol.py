"""The ReflectionRepository protocol lives in repositories.py."""

from __future__ import annotations

import importlib
import sys

import pytest


def test_repository_module_is_gone() -> None:
    """``etlalchemy.reflect.repository`` must no longer be importable."""
    sys.modules.pop("etlalchemy.reflect.repository", None)

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("etlalchemy.reflect.repository")


def test_protocol_is_exported_from_repositories() -> None:
    """The protocol declares the four cache operations."""
    from etlalchemy.reflect.repositories import ReflectionRepository

    assert hasattr(ReflectionRepository, "get")
    assert hasattr(ReflectionRepository, "get_entry")
    assert hasattr(ReflectionRepository, "save")
    assert hasattr(ReflectionRepository, "clear")


def test_reflect_package_exports_protocol_from_new_location() -> None:
    """The package re-exports the protocol from its new module."""
    from etlalchemy.reflect import ReflectionRepository

    assert ReflectionRepository.__module__ == "etlalchemy.reflect.repositories"
