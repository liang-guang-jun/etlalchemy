"""Casbin-backed authorization of the IAM context.

The policy rules live in the read model (``iam_casbin_rules``) so that a group
grant, a membership or a move is projected together with the rest of the state.
This module loads those rows into an in-memory Casbin enforcer and keeps it fresh:

* the read model bumps a generation counter on every Casbin write, so a request in
  this process sees its own projection immediately;
* the enforcer is also reloaded after ``reload_interval_seconds`` so another process
  (another uvicorn worker) converges without a message bus.
"""

from __future__ import annotations

import asyncio
from time import monotonic
from typing import TYPE_CHECKING
from uuid import UUID

from casbin import Enforcer, Model

from etlalchemy.iam.aggregates.types import Permission
from etlalchemy.shared.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from etlalchemy.iam.projection.view import IamView

POLICY_MODEL = """
[request_definition]
r = sub, dom, obj, act

[policy_definition]
p = sub, dom, obj, act

[role_definition]
g = _, _, _

[policy_effect]
e = some(where (p.eft == allow))

[matchers]
m = g(r.sub, p.sub, r.dom) && r.dom == p.dom && keyMatch2(r.obj, p.obj) && r.act == p.act
"""
"""Casbin model of the v1 policies.

``g`` carries ``(member, group, tenant)`` so nesting resolves transitively inside
one tenant. Resource groups (``g2``) are reserved for a later version: a policy
object is matched with ``keyMatch2`` only, so grants stay explicit.
"""


class CasbinAuthorizer:
    """Evaluates IAM policies with a cached, generation-aware Casbin enforcer."""

    def __init__(self, reload_interval_seconds: float = 1.0) -> None:
        """Builds an empty authorizer that loads its first policy on demand."""
        self._enforcer: Enforcer | None = None
        self._generation = -1
        self._loaded_at = 0.0
        self._reload_interval_seconds = max(0.0, reload_interval_seconds)
        self._lock = asyncio.Lock()

    async def refresh(self, view: IamView) -> None:
        """Rebuilds the enforcer from the rules stored in the read model."""
        rules = await view.list_casbin_rules()
        model = Model()
        model.load_model_from_text(POLICY_MODEL)
        enforcer = Enforcer(model)
        for rule in rules:
            if rule.ptype == "p":
                enforcer.add_policy(rule.v0, rule.v1, rule.v2, rule.v3)
            elif rule.ptype == "g":
                enforcer.add_grouping_policy(rule.v0, rule.v1, rule.v2)
        self._enforcer = enforcer
        self._generation = view.policy_generation()
        self._loaded_at = monotonic()
        get_logger("iam.authorization").debug(
            "policy.loaded",
            rules=len(rules),
            generation=self._generation,
        )

    async def ensure_fresh(self, view: IamView) -> None:
        """Reloads the policy when it is missing, outdated or older than the TTL."""
        if not self._is_stale(view):
            return
        async with self._lock:
            if not self._is_stale(view):
                return
            await self.refresh(view)

    async def enforce(
        self,
        view: IamView,
        user_id: UUID,
        tenant_id: UUID | None,
        obj: str,
        act: str,
    ) -> bool:
        """Returns whether the policy allows the action on the object."""
        await self.ensure_fresh(view)
        enforcer = self._enforcer
        if enforcer is None:  # pragma: no cover - ensure_fresh always loads one
            return False
        return bool(enforcer.enforce(str(user_id), str(tenant_id or ""), obj, act))

    async def implicit_permissions(
        self,
        view: IamView,
        user_id: UUID,
        tenant_id: UUID | None,
    ) -> frozenset[Permission]:
        """Returns the permissions the user inherits through its groups."""
        await self.ensure_fresh(view)
        enforcer = self._enforcer
        if enforcer is None:  # pragma: no cover - ensure_fresh always loads one
            return frozenset()
        rows = enforcer.get_implicit_permissions_for_user(str(user_id), str(tenant_id or ""))
        return frozenset(Permission(resource=row[2], action=row[3]) for row in rows)

    def _is_stale(self, view: IamView) -> bool:
        """Returns whether the cached policy must be rebuilt."""
        if self._enforcer is None:
            return True
        if view.policy_generation() != self._generation:
            return True
        return (monotonic() - self._loaded_at) >= self._reload_interval_seconds


__all__ = ["POLICY_MODEL", "CasbinAuthorizer"]
