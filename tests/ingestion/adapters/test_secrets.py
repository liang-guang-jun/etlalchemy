"""Tests for the secret adapters."""

from pathlib import Path

import pytest

from etlalchemy.ingestion.adapters.secrets_composite import CompositeSecretsResolver
from etlalchemy.ingestion.adapters.secrets_env import EnvSecretsProvider
from etlalchemy.ingestion.adapters.secrets_file import FileSecretsProvider
from etlalchemy.ingestion.aggregates.errors import UnsupportedCredentialSchemeError
from etlalchemy.ingestion.ports.secrets import SecretValue


async def test_secret_value_redacts_repr_and_refuses_str() -> None:
    """The secret value only exposes itself through its ``value`` attribute."""
    secret = SecretValue("s3cr3t")

    assert secret.value == "s3cr3t"
    assert repr(secret) == "SecretValue(***)"
    with pytest.raises(TypeError, match="no string form"):
        str(secret)


async def test_env_provider_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The env provider returns the named environment variable."""
    monkeypatch.setenv("DBX_TOKEN", "from-env")

    assert (await EnvSecretsProvider().get("DBX_TOKEN")).value == "from-env"


async def test_file_provider_reads_a_root_relative_file(tmp_path: Path) -> None:
    """Relative paths are resolved under the configured root and stripped."""
    (tmp_path / "dbx-token").write_text("  from-file\n", encoding="utf-8")

    provider = FileSecretsProvider(tmp_path)

    assert (await provider.get("dbx-token")).value == "from-file"


async def test_file_provider_reads_an_absolute_path(tmp_path: Path) -> None:
    """Absolute paths ignore the configured root."""
    path = tmp_path / "token"
    path.write_text("absolute", encoding="utf-8")

    provider = FileSecretsProvider(tmp_path / "elsewhere")

    assert (await provider.get(str(path))).value == "absolute"


async def test_composite_resolver_routes_by_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``scheme:path`` reference is dispatched to the matching provider."""
    monkeypatch.setenv("DBX_TOKEN", "from-env")
    resolver = CompositeSecretsResolver({"env": EnvSecretsProvider()})

    assert (await resolver.resolve("env:DBX_TOKEN")).value == "from-env"


async def test_composite_resolver_rejects_unknown_schemes() -> None:
    """References without a known scheme are rejected."""
    resolver = CompositeSecretsResolver({})

    with pytest.raises(UnsupportedCredentialSchemeError, match="vault"):
        await resolver.resolve("vault:secret/x")
    with pytest.raises(UnsupportedCredentialSchemeError):
        await resolver.resolve("no-scheme")
