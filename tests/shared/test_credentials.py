"""Tests of the shared credential reference helpers."""

from __future__ import annotations

from etlalchemy.shared.credentials import profile_credential, profile_reference


def test_a_profile_reference_names_the_profile() -> None:
    """A ``profile:`` reference yields the profile name without the prefix."""
    assert profile_reference("profile:team") == "team"


def test_a_profile_reference_may_use_the_default_profile() -> None:
    """An empty name keeps the SDK default resolution."""
    assert profile_reference("profile:") == ""
    assert profile_reference("profile:  ") == ""


def test_a_profile_reference_is_trimmed() -> None:
    """Surrounding whitespace does not reach the profile name."""
    assert profile_reference("  profile: team  ") == "team"


def test_other_references_are_not_profiles() -> None:
    """``env:``, ``file:`` and a missing reference stay untouched."""
    assert profile_reference("env:DBX_TOKEN") is None
    assert profile_reference("file:token") is None
    assert profile_reference(None) is None


def test_a_profile_credential_is_a_reference() -> None:
    """A profile name round-trips through the reference form."""
    assert profile_credential("team") == "profile:team"
    assert profile_reference(profile_credential("team")) == "team"
    assert profile_credential("") == "profile:"
