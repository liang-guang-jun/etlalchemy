"""File repositories require an explicit directory."""

from __future__ import annotations

from pathlib import Path

import pytest
from etlalchemy.reflect.repositories import (
    InMemoryReflectionRepository,
    JsonReflectionRepository,
    YamlReflectionRepository,
)


def test_json_repository_requires_directory() -> None:
    """A JSON cache without a directory is a usage error."""
    with pytest.raises(ValueError, match="directory"):
        JsonReflectionRepository()


def test_yaml_repository_requires_directory() -> None:
    """A YAML cache without a directory is a usage error."""
    pytest.importorskip("yaml")
    with pytest.raises(ValueError, match="directory"):
        YamlReflectionRepository()


def test_json_repository_uses_given_directory(tmp_path: Path) -> None:
    """The cache file lands in the directory the caller chose."""
    repository = JsonReflectionRepository(tmp_path)

    repository.save("k", (), complete=True)

    assert (tmp_path / "k.json").is_file()


def test_json_repository_does_not_read_xdg_cache_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``XDG_CACHE_HOME`` never supplies a default directory."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))

    with pytest.raises(ValueError, match="directory"):
        JsonReflectionRepository()

    assert not (tmp_path / "xdg").exists()


def test_in_memory_repository_still_works_without_directory() -> None:
    """The in-memory cache touches no disk and needs no directory."""
    assert len(InMemoryReflectionRepository()) == 0
