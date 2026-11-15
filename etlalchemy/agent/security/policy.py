"""Tool exposure and approval policy of the agent."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Literal

from etlalchemy.agent.settings import AgentRuntimeSettings, ApprovalRule

Decision = Literal["auto", "require_approval", "deny"]


@dataclass(frozen=True)
class ToolPolicy:
    """How one tool call is handled."""

    decision: Decision
    """Whether the call runs, needs an approval or is refused."""
    reason: str = ""
    """Human-readable justification, shown to the approver."""
    destructive: bool = False
    """Whether the tool was annotated as destructive."""
    read_only: bool = False
    """Whether the tool was annotated as read-only."""
    defaulted: bool = False
    """Whether no rule matched and the configured default produced the decision.

    A reader who turned auto-approve on may overrule this fallback, while a
    decision a rule declares stays in force.
    """


class ApprovalPolicy:
    """Decides what the runtime does with one tool call.

    A read-only tool always runs. A destructive tool is decided by the first
    matching rule; without a match the configured default applies, which is
    ``deny`` unless a deployment changes it.
    """

    def __init__(self, settings: AgentRuntimeSettings) -> None:
        """Stores the settings the decisions are read from."""
        self._settings = settings

    def decide(
        self,
        tool_name: str,
        *,
        read_only: bool,
        destructive: bool,
        has_hints: bool = True,
        context: dict[str, str] | None = None,
    ) -> ToolPolicy:
        """Returns the policy of one tool call.

        Args:
            tool_name: Name of the tool being called.
            read_only: Whether the MCP tool carries ``readOnlyHint``.
            destructive: Whether the MCP tool carries ``destructiveHint``.
            has_hints: Whether the tool carries any annotation at all.
            context: Values the rules may require, for example ``tenant_env``.

        Returns:
            The decision, its reason, and the annotations it was derived from.
        """
        if read_only:
            return ToolPolicy(
                decision="auto",
                reason="read-only tool",
                destructive=destructive,
                read_only=True,
            )
        facts = context or {}
        for rule in self._settings.approval_rules:
            if not self._matches(rule, tool_name, facts):
                continue
            return ToolPolicy(
                decision=rule.action,
                reason=f"approval rule {rule.match!r} -> {rule.action}",
                destructive=destructive,
            )
        if not destructive:
            if has_hints:
                return ToolPolicy(decision="auto", reason="tool is not destructive")
            return ToolPolicy(
                decision="require_approval",
                reason="tool has no MCP hint; fail closed and ask a human",
                destructive=destructive,
            )
        decision: Decision = "deny" if self._settings.approval_default == "deny" else "auto"
        return ToolPolicy(
            decision=decision,
            reason="default approval policy",
            destructive=destructive,
            defaulted=True,
        )

    def _matches(
        self,
        rule: ApprovalRule,
        tool_name: str,
        facts: dict[str, str],
    ) -> bool:
        """Returns whether a rule applies to the tool and the current context."""
        if not fnmatch.fnmatchcase(tool_name, rule.match):
            return False
        return all(facts.get(key) == value for key, value in rule.when.items())
