"""Tests of the approval policy."""

from __future__ import annotations

from etlalchemy.agent.security.policy import ApprovalPolicy
from etlalchemy.agent.settings import AgentRuntimeSettings, ApprovalRule


def make_policy(
    *rules: ApprovalRule,
    default: str = "deny",
) -> ApprovalPolicy:
    """Builds a policy with the given rules and default."""
    return ApprovalPolicy(
        AgentRuntimeSettings(approval_default=default, approval_rules=rules),
    )


def test_read_only_tools_run_without_approval() -> None:
    """``readOnlyHint`` always wins, even for a destructive default."""
    policy = make_policy(ApprovalRule(match="*", action="deny"))
    decision = policy.decide("list_models", read_only=True, destructive=False)
    assert decision.decision == "auto"
    assert decision.read_only is True


def test_destructive_tool_defaults_to_deny() -> None:
    """Without a matching rule a destructive tool is refused."""
    policy = make_policy()
    decision = policy.decide("discard_catalog", read_only=False, destructive=True)
    assert decision.decision == "deny"
    assert decision.destructive is True
    assert decision.defaulted is True


def test_rule_decision_is_not_the_default() -> None:
    """A rule that refuses the call is a configured decision, not a fallback."""
    policy = make_policy(ApprovalRule(match="remove_*", action="deny"))
    decision = policy.decide("remove_diagram", read_only=False, destructive=True)
    assert decision.decision == "deny"
    assert decision.defaulted is False


def test_rule_requests_an_approval() -> None:
    """A matching rule produces the action it declares."""
    policy = make_policy(ApprovalRule(match="discard_*", action="require_approval"))
    decision = policy.decide("discard_catalog", read_only=False, destructive=True)
    assert decision.decision == "require_approval"
    assert "discard_*" in decision.reason
    assert decision.defaulted is False


def test_rule_conditions_must_hold() -> None:
    """A rule with a condition only matches when the context provides it."""
    policy = make_policy(
        ApprovalRule(
            match="change_*",
            when={"tenant_env": "prod"},
            action="require_approval",
        ),
        default="allow",
    )
    assert policy.decide("change_schema", read_only=False, destructive=False).decision == "auto"
    prod = policy.decide(
        "change_schema",
        read_only=False,
        destructive=False,
        context={"tenant_env": "prod"},
    )
    assert prod.decision == "require_approval"


def test_first_matching_rule_wins() -> None:
    """Rules are evaluated in order."""
    policy = make_policy(
        ApprovalRule(match="discard_*", action="deny"),
        ApprovalRule(match="*", action="require_approval"),
    )
    assert policy.decide("discard_catalog", read_only=False, destructive=True).decision == "deny"
    assert (
        policy.decide("other", read_only=False, destructive=True).decision == "require_approval"
    )


def test_tool_without_any_hint_requires_an_approval() -> None:
    """A tool that carries no annotation is not trusted to run on its own."""
    policy = make_policy()
    decision = policy.decide(
        "mystery_tool",
        read_only=False,
        destructive=False,
        has_hints=False,
    )
    assert decision.decision == "require_approval"
    assert "hint" in decision.reason


def test_hinted_non_destructive_tool_runs() -> None:
    """An explicit non-destructive annotation is trusted."""
    policy = make_policy()
    decision = policy.decide(
        "list_things",
        read_only=False,
        destructive=False,
        has_hints=True,
    )
    assert decision.decision == "auto"


def test_rule_still_wins_over_a_missing_hint() -> None:
    """An explicit rule decides even when the tool advertises nothing."""
    policy = make_policy(ApprovalRule(match="mystery_*", action="deny"))
    decision = policy.decide(
        "mystery_tool",
        read_only=False,
        destructive=False,
        has_hints=False,
    )
    assert decision.decision == "deny"
