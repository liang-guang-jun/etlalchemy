"""Shared fixtures for the assembly-layer tests."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from etlalchemy.app.bootstrap import Container


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Points the settings loader at a temporary configuration directory."""
    directory = tmp_path / "config"
    directory.mkdir()
    (directory / "config.example.yaml").write_text(
        f"""\
database:
  backend: sqlite
  sqlite_path: {tmp_path / "default.db"}
api:
  port: 8000
mcp:
  require_auth: false
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ETLALCHEMY_CONFIG_DIR", str(directory))
    monkeypatch.setenv("ETLALCHEMY_ENV", "test")
    yield directory


@pytest.fixture
def write_config(config_dir: Path) -> Callable[[str], None]:
    """Returns a helper that writes the environment-specific config file."""

    def write(text: str) -> None:
        (config_dir / "config.test.yaml").write_text(text, encoding="utf-8")

    return write


@pytest.fixture
def container() -> Iterator[Container]:
    """Returns a fresh container whose providers resolve lazily."""
    container = Container()
    try:
        yield container
    finally:
        container.unwire()
