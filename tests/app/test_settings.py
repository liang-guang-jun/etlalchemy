"""Tests for the layered settings loader."""

import base64
import os
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from etlalchemy.app.config.loader import CONFIG_FILES_ENV, ConfigError, load_settings
from etlalchemy.app.config.settings import AppSettings, IamSettings, LlmBootstrapSettings


def test_context_without_override_inherits_global_database(
    write_config: Callable[[str], None],
) -> None:
    """A context without a database block returns the global settings object."""
    write_config("database:\n  backend: sqlite\n  sqlite_path: ./global.db\n")

    settings = load_settings("test")

    assert settings.database_for("catalog") is settings.database


def test_context_override_merges_fields(
    config_dir: Path,
    write_config: Callable[[str], None],
) -> None:
    """A context override only replaces the fields it sets."""
    write_config(
        f"""\
database:
  backend: sqlite
  sqlite_path: {config_dir.parent / "global.db"}
catalog:
  database:
    sqlite_path: {config_dir.parent / "catalog.db"}
"""
    )

    resolved = load_settings("test").database_for("catalog")

    assert resolved.sqlite_path == str(config_dir.parent / "catalog.db")
    assert resolved.backend == "sqlite"


def test_postgres_override_requires_a_dsn(
    write_config: Callable[[str], None],
) -> None:
    """Switching a context to Postgres without a DSN fails validation."""
    write_config("catalog:\n  database:\n    backend: postgres\n")

    settings = load_settings("test")

    with pytest.raises(ValidationError, match="postgres_dsn"):
        settings.database_for("catalog")


def test_environment_variables_override_yaml(
    write_config: Callable[[str], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Environment variables win over the YAML files."""
    write_config("catalog:\n  database:\n    sqlite_path: ./yaml.db\n")
    monkeypatch.setenv("ETLALCHEMY_CATALOG__DATABASE__SQLITE_PATH", "/tmp/from-env.db")

    settings = load_settings("test")

    assert settings.database_for("catalog").sqlite_path == "/tmp/from-env.db"


def test_sqlite_environment_uses_the_async_sqlalchemy_module(
    config_dir: Path,
) -> None:
    """The SQLite environment targets the aiosqlite engine of the async module."""
    settings = load_settings("test")

    env = settings.database.to_eventsourcing_env()

    assert env["PERSISTENCE_MODULE"] == "eventsourcing.asyncio.sqlalchemy"
    assert env["SQLALCHEMY_URL"] == f"sqlite+aiosqlite:///{config_dir.parent / 'default.db'}"
    assert env["CREATE_TABLE"] == "y"


def test_dotenv_file_is_exported_before_the_configuration_is_resolved(
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``.env`` next to the YAML files provides ``env:`` secret references."""
    name = "ETLALCHEMY_TEST_DOTENV_SECRET"
    monkeypatch.delenv(name, raising=False)
    (config_dir / ".env").write_text(f"{name}=from-dotenv\n", encoding="utf-8")
    try:
        load_settings("test")

        assert os.environ[name] == "from-dotenv"
    finally:
        os.environ.pop(name, None)


def test_real_environment_wins_over_the_dotenv_file(
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A variable already exported by the process is not replaced by ``.env``."""
    name = "ETLALCHEMY_TEST_DOTENV_SECRET"
    monkeypatch.setenv(name, "from-process")
    (config_dir / ".env").write_text(f"{name}=from-dotenv\n", encoding="utf-8")

    load_settings("test")

    assert os.environ[name] == "from-process"


def test_extra_config_files_override_the_layered_defaults(config_dir: Path) -> None:
    """Explicit files are merged in order and win over the layered defaults."""
    first = config_dir / "first.yaml"
    first.write_text("api:\n  host: 1.2.3.4\n  port: 9000\n", encoding="utf-8")
    second = config_dir / "second.yaml"
    second.write_text("api:\n  port: 9100\n", encoding="utf-8")

    settings = load_settings("test", [first, second])

    assert (settings.api.host, settings.api.port) == ("1.2.3.4", 9100)


def test_extra_config_files_are_merged_deeply(config_dir: Path) -> None:
    """An overlay only replaces the nested keys it sets."""
    base = config_dir / "base.yaml"
    base.write_text(
        "catalog:\n  projection:\n    enabled: false\n"
        "    tracking_table_name: custom_tracking\n",
        encoding="utf-8",
    )
    overlay = config_dir / "overlay.yaml"
    overlay.write_text("catalog:\n  projection:\n    enabled: true\n", encoding="utf-8")

    settings = load_settings("test", [base, overlay])

    assert settings.catalog.projection.enabled is True
    assert settings.catalog.projection.tracking_table_name == "custom_tracking"


def test_extra_config_files_can_come_from_the_environment(
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exported file list is used when no explicit file is given."""
    path = config_dir / "exported.yaml"
    path.write_text("api:\n  port: 1234\n", encoding="utf-8")
    monkeypatch.setenv(CONFIG_FILES_ENV, str(path))

    assert load_settings("test").api.port == 1234


def test_missing_extra_config_file_is_rejected(config_dir: Path) -> None:
    """An explicitly requested file must exist."""
    with pytest.raises(ConfigError, match="not found"):
        load_settings("test", [config_dir / "missing.yaml"])


def test_ingestion_inherits_the_global_database(
    write_config: Callable[[str], None],
) -> None:
    """Without a database block the ingestion context shares the global settings."""
    write_config("database:\n  backend: sqlite\n  sqlite_path: ./global.db\n")

    settings = load_settings("test")

    assert settings.database_for("ingestion") is settings.database


def test_ingestion_projection_uses_its_own_tracking_table(
    write_config: Callable[[str], None],
) -> None:
    """Ingestion has a context-specific tracking table default."""
    write_config("ingestion:\n  projection:\n    enabled: false\n")

    settings = load_settings("test")

    assert settings.ingestion.projection.enabled is False
    assert settings.ingestion.projection.tracking_table_name == "ingestion_projection_tracking"


def test_ingestion_override_merges_fields(
    config_dir: Path,
    write_config: Callable[[str], None],
) -> None:
    """An ingestion override only replaces the fields it sets."""
    write_config(
        f"""\
database:
  backend: sqlite
  sqlite_path: {config_dir.parent / "global.db"}
ingestion:
  database:
    sqlite_path: {config_dir.parent / "ingestion.db"}
"""
    )

    resolved = load_settings("test").database_for("ingestion")

    assert resolved.sqlite_path == str(config_dir.parent / "ingestion.db")
    assert resolved.backend == "sqlite"


def test_vocabulary_inherits_the_global_database(
    write_config: Callable[[str], None],
) -> None:
    """Without a database block the vocabulary context shares the global settings."""
    write_config("database:\n  backend: sqlite\n  sqlite_path: ./global.db\n")

    settings = load_settings("test")

    assert settings.database_for("vocabulary") is settings.database


def test_vocabulary_projection_uses_its_own_tracking_table(
    write_config: Callable[[str], None],
) -> None:
    """Vocabulary has a context-specific tracking table default."""
    write_config("vocabulary:\n  projection:\n    enabled: false\n")

    settings = load_settings("test")

    assert settings.vocabulary.projection.enabled is False
    assert settings.vocabulary.projection.tracking_table_name == "vocabulary_projection_tracking"


def test_semantic_inherits_the_global_database(
    write_config: Callable[[str], None],
) -> None:
    """Without a database block the semantic context shares the global settings."""
    write_config("database:\n  backend: sqlite\n  sqlite_path: ./global.db\n")

    settings = load_settings("test")

    assert settings.database_for("semantic") is settings.database


def test_semantic_projection_uses_its_own_tracking_table(
    write_config: Callable[[str], None],
) -> None:
    """Semantic has a context-specific tracking table default."""
    write_config("semantic:\n  projection:\n    enabled: false\n")

    settings = load_settings("test")

    assert settings.semantic.projection.enabled is False
    assert settings.semantic.projection.tracking_table_name == "semantic_projection_tracking"


CIPHER_KEY = base64.b64encode(b"0" * 32).decode()
"""Fixed 32-byte AES key used by the cipher key tests."""


def test_cipher_key_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a configured key events stay in plaintext."""
    monkeypatch.delenv("ETLALCHEMY_CIPHER_KEY", raising=False)

    assert AppSettings().cipher_key is None


@pytest.mark.parametrize("size", [16, 24, 32])
def test_cipher_key_accepts_valid_base64_keys(size: int) -> None:
    """A key decoding to 16, 24 or 32 bytes is accepted verbatim."""
    key = base64.b64encode(b"k" * size).decode()

    assert AppSettings(cipher_key=key).cipher_key == key


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("not base64!", id="not-base64"),
        pytest.param(base64.b64encode(b"k" * 8).decode(), id="8-bytes"),
        pytest.param(base64.b64encode(b"k" * 17).decode(), id="17-bytes"),
    ],
)
def test_invalid_cipher_key_is_rejected(value: str) -> None:
    """A malformed key fails validation when the settings are constructed."""
    with pytest.raises(ValidationError, match="cipher_key"):
        AppSettings(cipher_key=value)


def test_cipher_key_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The key can be supplied through ``ETLALCHEMY_CIPHER_KEY``."""
    monkeypatch.setenv("ETLALCHEMY_CIPHER_KEY", CIPHER_KEY)

    assert AppSettings().cipher_key == CIPHER_KEY


def test_logging_defaults_match_the_documented_contract() -> None:
    """A configuration without a logging block logs INFO to stdout with colours."""
    settings = AppSettings()

    assert settings.logging.level == "INFO"
    assert settings.logging.mode == "stdout"
    assert settings.logging.color is True


def test_logging_reads_the_yaml_block(write_config: Callable[[str], None]) -> None:
    """The nested YAML block configures level, mode and colour."""
    write_config("logging:\n  level: DEBUG\n  mode: json\n  color: false\n")

    settings = load_settings("test")

    assert (settings.logging.level, settings.logging.mode, settings.logging.color) == (
        "DEBUG",
        "json",
        False,
    )


def test_logging_environment_overrides_the_file(
    write_config: Callable[[str], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ETLALCHEMY_LOGGING__*`` variables win over the YAML values."""
    write_config("logging:\n  mode: stdout\n  level: INFO\n")
    monkeypatch.setenv("ETLALCHEMY_LOGGING__MODE", "json")
    monkeypatch.setenv("ETLALCHEMY_LOGGING__LEVEL", "debug")

    settings = load_settings("test")

    assert settings.logging.mode == "json"
    assert settings.logging.level == "debug"


def test_logging_quiet_defaults_cover_the_noisy_third_parties() -> None:
    """The default quiet list keeps the third-party libraries out of the log."""
    assert set(AppSettings().logging.quiet) == {
        "uvicorn.access",
        "httpx",
        "httpcore",
        "databricks.sdk",
        "psycopg",
        "sqlalchemy.engine",
    }
    assert AppSettings().logging.loggers == {}


def test_logging_quiet_and_loggers_read_from_yaml(write_config: Callable[[str], None]) -> None:
    """``quiet`` and ``loggers`` are plain nested YAML values."""
    write_config(
        """\
logging:
  quiet:
    - httpx
  loggers:
    uvicorn: WARNING
"""
    )

    settings = load_settings("test")

    assert settings.logging.quiet == ["httpx"]
    assert settings.logging.loggers == {"uvicorn": "WARNING"}


def test_logging_loggers_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A JSON object in ``ETLALCHEMY_LOGGING__LOGGERS`` sets per-logger levels."""
    monkeypatch.setenv("ETLALCHEMY_LOGGING__LOGGERS", '{"uvicorn": "DEBUG"}')
    monkeypatch.setenv("ETLALCHEMY_LOGGING__QUIET", '["httpx", "httpcore"]')

    settings = load_settings("test")

    # The variables win over the files; other file-provided entries may remain.
    assert settings.logging.loggers["uvicorn"] == "DEBUG"
    assert settings.logging.quiet == ["httpx", "httpcore"]


def test_bearer_token_prefix_has_a_documented_default() -> None:
    """Both delivery layers accept the ``iam_sess_`` prefix unless configured."""
    assert AppSettings().iam.bearer_token_prefix == "iam_sess_"


def test_mcp_requires_authentication_by_default() -> None:
    """The MCP server refuses anonymous clients unless the setting disables it."""
    assert AppSettings().mcp.require_auth is True


def test_mcp_authentication_can_be_disabled_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ETLALCHEMY_MCP__REQUIRE_AUTH`` turns the check off for local development."""
    monkeypatch.setenv("ETLALCHEMY_MCP__REQUIRE_AUTH", "false")

    assert load_settings("test").mcp.require_auth is False


def test_session_refresh_lead_has_a_documented_default() -> None:
    """Clients refresh five minutes before expiry unless configured otherwise."""
    assert AppSettings().iam.session_refresh_lead_minutes == 5


def test_session_refresh_lead_reads_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ETLALCHEMY_IAM__SESSION_REFRESH_LEAD_MINUTES`` sets the lead time."""
    monkeypatch.setenv("ETLALCHEMY_IAM__SESSION_REFRESH_LEAD_MINUTES", "7")

    assert load_settings("test").iam.session_refresh_lead_minutes == 7


@pytest.mark.parametrize("value", [0, -1, 60])
def test_session_refresh_lead_must_stay_below_the_shortest_session(value: int) -> None:
    """A lead outside ``[1, shortest lifetime)`` would make a client refresh in a loop."""
    with pytest.raises(ValidationError, match="session_refresh_lead_minutes"):
        IamSettings(session_refresh_lead_minutes=value)


def test_cors_origins_default_to_an_empty_list() -> None:
    """Without configured origins the API installs no CORS middleware."""
    assert AppSettings().api.cors_origins == []


def test_the_agent_calls_the_mcp_server_in_process_by_default() -> None:
    """A single-process deployment needs no URL, port or token.

    ``http`` stays available for split deployments, so the default has to be the
    one that cannot drift from the port the server actually listens on.
    """
    assert AppSettings().agent.mcp_transport == "in_process"


def test_the_agent_transport_can_be_switched_to_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ETLALCHEMY_AGENT__MCP_TRANSPORT=http`` restores the network hop."""
    monkeypatch.setenv("ETLALCHEMY_AGENT__MCP_TRANSPORT", "http")
    monkeypatch.setenv("ETLALCHEMY_AGENT__MCP_URL", "http://agent-host:9000/mcp")

    settings = load_settings("test")

    assert settings.agent.mcp_transport == "http"
    assert settings.agent.mcp_url == "http://agent-host:9000/mcp"


def test_the_llm_bootstrap_accepts_a_databricks_profile() -> None:
    """A profile supplies the host, so the bootstrap endpoint may be omitted."""
    settings = LlmBootstrapSettings(
        name="databricks",
        kind="databricks_ai_gateway",
        credential_ref="profile:team",
        default_model="databricks-claude-sonnet-4-5",
    )

    assert settings.endpoint is None


def test_the_llm_bootstrap_rejects_a_profile_for_openai() -> None:
    """Only the Databricks gateway understands a CLI profile."""
    with pytest.raises(ValidationError, match="profile"):
        LlmBootstrapSettings(
            name="openai",
            kind="openai",
            credential_ref="profile:team",
        )
