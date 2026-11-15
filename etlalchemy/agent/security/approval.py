"""The human-in-the-loop decision a paused run resumes with."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from langgraph.types import Command


@dataclass(frozen=True)
class ApprovalDecision:
    """One answer to an approval request."""

    approved: bool
    """Whether the tool call may run."""
    reason: str = ""
    """Optional justification recorded with the decision."""

    def as_resume(self) -> dict[str, Any]:
        """Returns the value the interrupted tool reads when the run resumes."""
        return {"approved": self.approved, "reason": self.reason}


def resume_command(decision: ApprovalDecision) -> Command[Any]:
    """Builds the LangGraph command that resumes a paused run.

    Args:
        decision: The answer the approver gave.

    Returns:
        A command the graph accepts in place of a new input.
    """
    return Command(resume=decision.as_resume())


def approval_payload(
    *,
    run_id: UUID,
    approval_id: UUID,
    tool: str,
    args_hash: str,
    reason: str,
) -> dict[str, Any]:
    """Builds the payload an interrupted tool hands to the approver."""
    return {
        "approval_id": str(approval_id),
        "run_id": str(run_id),
        "tool": tool,
        "args_hash": args_hash,
        "reason": reason,
    }
