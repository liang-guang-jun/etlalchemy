"""Application service exposing the LLM provider use cases."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

import structlog
from eventsourcing.application import AggregateNotFoundError
from eventsourcing.utils import EnvType

from etlalchemy._vendor.eventsourcing.asyncio.application import AsyncApplication
from etlalchemy.iam.aggregates.errors import PermissionDeniedError
from etlalchemy.llm_config.aggregates.errors import (
    DuplicateProviderNameError,
    InvalidSharingError,
    ProviderCredentialError,
    UnknownProviderError,
    UnknownShareTargetError,
)
from etlalchemy.llm_config.aggregates.provider import LlmProvider
from etlalchemy.llm_config.projection.view import (
    LlmProviderView,
    ProviderDefaultRow,
    ProviderDetail,
    ProviderRow,
    ProviderShareRow,
)
from etlalchemy.shared.credentials import profile_reference
from etlalchemy.shared.logging import get_logger

if TYPE_CHECKING:
    from etlalchemy.llm_config.ports.authorization import (
        LlmConfigAuthorizationPort,
        SessionUser,
    )
    from etlalchemy.llm_config.ports.secrets import SecretsResolver

SYSTEM_USER_ID = UUID(int=0)
"""Owner of a provider that the configuration file bootstrapped.

No interactive caller exists at startup, so the system principal owns it and the
aggregate keeps a non-optional owner.
"""

WRITE_PERMISSION = ("llm_provider", "write")
"""Permission that lets a caller manage providers it does not own."""


def _same_credential(
    provider: LlmProvider,
    credential_ref: str | None,
    token: str | None,
) -> bool:
    """Returns whether the provider already carries the configured credential."""
    if token is not None:
        return provider.token == token and provider.credential_ref is None
    return provider.credential_ref == credential_ref and provider.token is None


@dataclass(frozen=True)
class LlmConfigOptions:
    """Policy knobs of the LLM provider context."""

    max_providers_per_user: int = 50
    """Hard cap on the live providers one user may own."""
    default_page_size: int = 50
    """Page size used when a read does not specify one."""
    max_page_size: int = 200
    """Upper bound of every page size."""


class LlmConfigApplication(AsyncApplication[UUID]):
    """Application service for the LLM provider context.

    A provider is visible to its owner, to every user or group it is shared with
    and to everybody when it is public. Writing needs ownership, the
    ``llm_provider:write`` permission or the system administrator flag.
    """

    name = "llm_config_application"
    """Application name; the eventsourcing factories derive table names from it."""

    def __init__(
        self,
        view: LlmProviderView,
        iam: LlmConfigAuthorizationPort,
        secrets: SecretsResolver,
        options: LlmConfigOptions | None = None,
        env: EnvType | None = None,
    ) -> None:
        """Wires the read model, the IAM port and the secret resolver."""
        super().__init__(env=env)
        self._view = view
        self._iam = iam
        self._secrets = secrets
        self._options = options or LlmConfigOptions()
        self._log: structlog.stdlib.BoundLogger = get_logger("llm_config.application")

    # -- writes -------------------------------------------------------------

    async def create_llm_provider(
        self,
        session_id: UUID,
        name: str,
        kind: str,
        endpoint: str | None = None,
        credential_ref: str | None = None,
        token: str | None = None,
        default_model: str = "",
        options: Mapping[str, str] | None = None,
        tenant_id: UUID | None = None,
        is_public: bool = False,
    ) -> UUID:
        """Creates a provider and returns its id."""
        self._log.info("llm_config.provider.create start", name=name, kind=kind)
        session = await self._iam.session_user(session_id)
        if is_public and not await self._is_writer(session):
            msg = "only an administrator may create a public LLM provider"
            raise PermissionDeniedError(msg)
        if await self._view.find_provider_by_name(name.strip()) is not None:
            msg = f"LLM provider {name!r} already exists"
            raise DuplicateProviderNameError(msg)
        owned = await self._view.list_providers(owner_user_id=session.user_id)
        if len(owned) >= self._options.max_providers_per_user:
            msg = (
                f"user {session.user_id} already owns "
                f"{self._options.max_providers_per_user} LLM providers"
            )
            raise DuplicateProviderNameError(msg)
        resolved_tenant = self._resolve_tenant(session, tenant_id, is_public)
        provider = LlmProvider(
            name=name,
            kind=kind,
            owner_user_id=session.user_id,
            endpoint=endpoint,
            credential_ref=credential_ref,
            token=token,
            default_model=default_model,
            options=options,
            tenant_id=resolved_tenant,
            is_public=is_public,
        )
        await self.save(provider)
        self._log.info("llm_config.provider.create done", provider_id=str(provider.id))
        return provider.id

    async def change_llm_provider(
        self,
        session_id: UUID,
        provider_id: UUID,
        name: str | None = None,
        endpoint: str | None = None,
        default_model: str | None = None,
        options: Mapping[str, str] | None = None,
    ) -> None:
        """Changes the metadata of a provider; the credential is not touched."""
        self._log.info("llm_config.provider.change start", provider_id=str(provider_id))
        session = await self._iam.session_user(session_id)
        provider = await self._provider(provider_id)
        await self._require_writer(session, provider)
        if name is None and endpoint is None and default_model is None and options is None:
            msg = "change_llm_provider requires at least one field"
            raise ValueError(msg)
        if name is not None and name.strip() != provider.name:
            existing = await self._view.find_provider_by_name(name.strip())
            if existing is not None and existing.provider_id != provider_id:
                msg = f"LLM provider {name!r} already exists"
                raise DuplicateProviderNameError(msg)
            provider.rename(name)
        if endpoint is not None:
            provider.change_endpoint(endpoint)
        if default_model is not None:
            provider.change_default_model(default_model)
        if options is not None:
            provider.change_options(options)
        await self.save(provider)
        self._log.info("llm_config.provider.change done", provider_id=str(provider_id))

    async def rotate_llm_credential(
        self,
        session_id: UUID,
        provider_id: UUID,
        credential_ref: str | None = None,
        token: str | None = None,
    ) -> None:
        """Replaces the credential of a provider with exactly one new source."""
        self._log.info("llm_config.provider.rotate start", provider_id=str(provider_id))
        session = await self._iam.session_user(session_id)
        provider = await self._provider(provider_id)
        await self._require_writer(session, provider)
        provider.rotate_credential(credential_ref, token)
        await self.save(provider)
        self._log.info("llm_config.provider.rotate done", provider_id=str(provider_id))

    async def share_llm_provider(
        self,
        session_id: UUID,
        provider_id: UUID,
        user_ids: Iterable[UUID] | None = None,
        group_ids: Iterable[UUID] | None = None,
    ) -> None:
        """Replaces the users and groups a provider is shared with.

        Sharing is only possible for a private provider: a public one is already
        available to everybody.
        """
        self._log.info("llm_config.provider.share start", provider_id=str(provider_id))
        session = await self._iam.session_user(session_id)
        provider = await self._provider(provider_id)
        await self._require_writer(session, provider)
        if provider.is_public:
            msg = "a public LLM provider cannot be shared selectively"
            raise InvalidSharingError(msg)
        checked_users = list(dict.fromkeys(user_ids or []))
        checked_groups = list(dict.fromkeys(group_ids or []))
        for user_id in checked_users:
            if not await self._iam.user_exists(user_id):
                msg = f"user {user_id} does not exist"
                raise UnknownShareTargetError(msg)
        for group_id in checked_groups:
            if not await self._iam.group_exists(group_id):
                msg = f"group {group_id} does not exist in this tenant"
                raise UnknownShareTargetError(msg)
        provider.set_sharing(checked_users, checked_groups)
        await self.save(provider)
        self._log.info("llm_config.provider.share done", provider_id=str(provider_id))

    async def set_default_llm_provider(
        self,
        session_id: UUID,
        provider_id: UUID,
        scope: str = "user",
        target_id: UUID | None = None,
    ) -> None:
        """Makes a provider the default of the given scope.

        The provider that held the pointer before is cleared in the same unit of
        work, so a scope never has two defaults.
        """
        self._log.info(
            "llm_config.provider.default.start",
            provider_id=str(provider_id),
            scope=scope,
        )
        session = await self._iam.session_user(session_id)
        provider = await self._provider(provider_id)
        resolved_target = await self._checked_default_target(session, scope, target_id)
        if not await self._can_use(session, provider):
            msg = f"the caller may not use LLM provider {provider_id}"
            raise PermissionDeniedError(msg)
        aggregates: list[LlmProvider] = []
        previous = await self._view.find_default_provider(scope, resolved_target)
        if previous is not None and previous.provider_id != provider_id:
            cleared = await self._provider(previous.provider_id)
            self._mark_default(cleared, scope, resolved_target, False)
            aggregates.append(cleared)
        self._mark_default(provider, scope, resolved_target, True)
        aggregates.append(provider)
        await self.save(*aggregates)
        self._log.info(
            "llm_config.provider.default.done",
            provider_id=str(provider_id),
            scope=scope,
        )

    async def clear_default_llm_provider(
        self,
        session_id: UUID,
        provider_id: UUID,
        scope: str = "user",
        target_id: UUID | None = None,
    ) -> None:
        """Clears a default pointer held by the given provider."""
        session = await self._iam.session_user(session_id)
        provider = await self._provider(provider_id)
        resolved_target = await self._checked_default_target(session, scope, target_id)
        self._mark_default(provider, scope, resolved_target, False)
        await self.save(provider)

    async def discard_llm_provider(self, session_id: UUID, provider_id: UUID) -> None:
        """Soft-deletes a provider and drops every pointer to it."""
        self._log.info("llm_config.provider.discard start", provider_id=str(provider_id))
        session = await self._iam.session_user(session_id)
        provider = await self._provider(provider_id)
        await self._require_writer(session, provider)
        provider.discard(session.user_id)
        await self.save(provider)
        self._log.info("llm_config.provider.discard done", provider_id=str(provider_id))

    # -- reads --------------------------------------------------------------

    async def list_llm_providers(
        self,
        session_id: UUID,
        include_public: bool = True,
        mine_only: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ProviderRow]:
        """Returns the providers the caller may see, ordered by name."""
        session = await self._iam.session_user(session_id)
        if mine_only:
            return await self._view.list_providers(owner_user_id=session.user_id)
        groups = await self._iam.effective_group_ids(session_id)
        visible: dict[UUID, ProviderRow] = {}
        for row in await self._view.list_providers(owner_user_id=session.user_id):
            visible[row.provider_id] = row
        for row in await self._view.list_providers_shared_with(
            user_id=session.user_id,
            group_ids=sorted(groups),
        ):
            visible.setdefault(row.provider_id, row)
        if include_public:
            for row in await self._view.list_providers(is_public=True):
                visible.setdefault(row.provider_id, row)
        ordered = sorted(visible.values(), key=lambda row: (row.name, str(row.provider_id)))
        size, start = self._page(limit, offset)
        return ordered[start : start + size]

    async def get_llm_provider(self, session_id: UUID, provider_id: UUID) -> ProviderDetail:
        """Returns one provider with its shares and default pointers."""
        session = await self._iam.session_user(session_id)
        row = await self._visible_row(session, provider_id)
        return await self._detail(row)

    async def resolve_llm_provider(
        self,
        user_id: UUID,
        tenant_id: UUID | None,
    ) -> ProviderRow | None:
        """Returns the provider a run should use, walking the fallback chain.

        The chain is: the user default, then the tenant default, then the system
        default, then the first public provider. ``None`` means the caller must
        fall back to the configuration file or refuse the run.

        Args:
            user_id: User the run acts for.
            tenant_id: Tenant the run acts in, or ``None``.

        Returns:
            The resolved provider row, or ``None`` when nothing is configured.
        """
        for scope, target in (("user", user_id), ("tenant", tenant_id)):
            if target is None:
                continue
            row = await self._view.find_default_provider(scope, target)
            if row is not None:
                return row
        system = await self._view.find_default_provider("system")
        if system is not None:
            return system
        public = await self._view.list_providers(is_public=True, limit=1)
        return public[0] if public else None

    async def created_provider_detail(self, provider_id: UUID) -> ProviderDetail:
        """Returns the detail of a just-created provider from the aggregate.

        The create route cannot read its own write back from the read model: the
        projection may not have applied the event yet. The aggregate carries the
        same values, so the response echoes them.

        Args:
            provider_id: ID the create use case returned.

        Returns:
            The provider detail, built without the read model.
        """
        provider = await self._provider(provider_id)
        row = ProviderRow(
            provider_id=provider.id,
            name=provider.name,
            kind=provider.kind,
            endpoint=provider.endpoint,
            credential_ref=provider.credential_ref,
            has_inline_credential=provider.token is not None,
            default_model=provider.default_model,
            options=dict(provider.options),
            owner_user_id=provider.owner_user_id,
            tenant_id=provider.tenant_id,
            is_public=provider.is_public,
            is_system_default=provider.is_system_default,
            created_at=provider.created_on,
        )
        return ProviderDetail(
            provider=row,
            shared_with_user_ids=list(provider.shared_with_user_ids),
            shared_with_group_ids=list(provider.shared_with_group_ids),
            default_for_tenant_ids=list(provider.default_for_tenant_ids),
            default_for_user_ids=list(provider.default_for_user_ids),
        )

    async def runtime_provider(
        self,
        provider_id: UUID | None,
        user_id: UUID,
        tenant_id: UUID | None,
    ) -> ProviderRow | None:
        """Returns the provider a run should use, without a session.

        An explicit provider wins; otherwise the fallback chain applies.

        Args:
            provider_id: Provider asked for explicitly, or ``None``.
            user_id: User the run acts for.
            tenant_id: Tenant the run acts in, or ``None``.

        Returns:
            The provider row, or ``None`` when nothing is configured.
        """
        if provider_id is None:
            return await self.resolve_llm_provider(user_id, tenant_id)
        return await self._view.get_provider(provider_id)

    async def credential_for(self, provider_id: UUID) -> str:
        """Returns the API key of a provider, resolving an external reference.

        Args:
            provider_id: ID of the provider.

        Returns:
            The plaintext credential, never logged by the caller.

        Raises:
            UnknownProviderError: If the provider does not exist.
            ProviderCredentialError: If the provider carries no credential or
                authenticates through a local profile instead of an API key.
        """
        provider = await self._provider(provider_id)
        if profile_reference(provider.credential_ref) is not None:
            msg = (
                f"LLM provider {provider_id} authenticates through a local "
                "Databricks CLI profile, not an API key"
            )
            raise ProviderCredentialError(msg)
        if provider.token is not None:
            return provider.token
        if provider.credential_ref is None:
            msg = f"LLM provider {provider_id} carries no credential"
            raise ProviderCredentialError(msg)
        secret = await self._secrets.resolve(provider.credential_ref)
        return secret.value

    # -- bootstrap ----------------------------------------------------------

    async def ensure_public_provider(
        self,
        name: str,
        kind: str,
        endpoint: str | None,
        credential_ref: str | None,
        token: str | None,
        default_model: str,
        options: Mapping[str, str] | None = None,
    ) -> UUID | None:
        """Ensures the configuration-file provider matches the file.

        This is the only write without a session: it runs during startup, before
        any user can log in. The provider named by the configuration file is
        authoritative: it is created when missing, even when another public
        provider exists, and an existing provider with the same name is updated
        to the endpoint, model, options and credential the file declares, so
        editing ``agent.llm`` takes effect on the next start.

        When no system default exists yet, the provider also becomes the system
        default, so a run resolves it instead of an older public one.

        Args:
            name: Name of the bootstrapped provider.
            kind: Provider kind.
            endpoint: Optional base URL.
            credential_ref: External secret reference, if any.
            token: Inline secret, if any.
            default_model: Model used when a request does not name one.
            options: Extra model options.

        Returns:
            The id of the existing or created provider, or ``None`` when the
            configuration file declares none.
        """
        existing = await self._view.find_provider_by_name(name)
        if existing is not None:
            return await self._sync_config_provider(
                existing.provider_id,
                kind=kind,
                endpoint=endpoint,
                credential_ref=credential_ref,
                token=token,
                default_model=default_model,
                options=options,
            )
        provider = LlmProvider(
            name=name,
            kind=kind,
            owner_user_id=SYSTEM_USER_ID,
            endpoint=endpoint,
            credential_ref=credential_ref,
            token=token,
            default_model=default_model,
            options=options,
            is_public=True,
        )
        if await self._view.find_default_provider("system") is None:
            provider.mark_system_default(True)
        await self.save(provider)
        self._log.info("llm_config.bootstrap.created", provider_id=str(provider.id))
        return provider.id

    async def _sync_config_provider(
        self,
        provider_id: UUID,
        *,
        kind: str,
        endpoint: str | None,
        credential_ref: str | None,
        token: str | None,
        default_model: str,
        options: Mapping[str, str] | None,
    ) -> UUID:
        """Applies the configuration file to an existing provider.

        Only the mutable fields are synchronised. ``kind`` and ``is_public`` are
        immutable in the aggregate, so a mismatch is reported instead of being
        overwritten; rename the provider in the configuration file to replace
        one of those.
        """
        provider = await self._provider(provider_id)
        if provider.kind != kind:
            self._log.warning(
                "llm_config.bootstrap.kind_mismatch",
                provider_id=str(provider_id),
                configured_kind=kind,
                registered_kind=provider.kind,
            )
            return provider_id
        changed: list[str] = []
        cleaned_endpoint = None if endpoint is None else endpoint.strip()
        if provider.endpoint != cleaned_endpoint:
            provider.change_endpoint(cleaned_endpoint)
            changed.append("endpoint")
        model = default_model.strip()
        if provider.default_model != model:
            provider.change_default_model(model)
            changed.append("default_model")
        wanted_options = {key: str(value) for key, value in (options or {}).items()}
        if dict(provider.options) != wanted_options:
            provider.change_options(wanted_options)
            changed.append("options")
        if not _same_credential(provider, credential_ref, token):
            provider.rotate_credential(credential_ref, token)
            changed.append("credential")
        if not provider.is_public:
            self._log.warning(
                "llm_config.bootstrap.not_public",
                provider_id=str(provider_id),
            )
        system_default = await self._view.find_default_provider("system")
        if system_default is None and not provider.is_system_default:
            provider.mark_system_default(True)
            changed.append("system_default")
        if changed:
            await self.save(provider)
            self._log.info(
                "llm_config.bootstrap.updated",
                provider_id=str(provider_id),
                fields=changed,
            )
        else:
            self._log.debug(
                "llm_config.bootstrap.present",
                provider_id=str(provider_id),
            )
        return provider_id

    # -- internals ----------------------------------------------------------

    async def _provider(self, provider_id: UUID) -> LlmProvider:
        """Returns a live provider aggregate, rejecting an unknown id."""
        try:
            provider: LlmProvider = await self.repository.get(provider_id)
        except AggregateNotFoundError as exc:
            msg = f"LLM provider {provider_id} does not exist"
            raise UnknownProviderError(msg) from exc
        if provider.is_discarded:
            msg = f"LLM provider {provider_id} does not exist"
            raise UnknownProviderError(msg)
        return provider

    async def _is_writer(self, session: SessionUser) -> bool:
        """Returns whether the caller may manage providers it does not own."""
        if session.is_system_admin:
            return True
        resource, action = WRITE_PERMISSION
        return await self._iam.authorize(session.session_id, resource, action)

    async def _require_writer(self, session: SessionUser, provider: LlmProvider) -> None:
        """Rejects a caller that may not change the given provider."""
        if provider.owner_user_id == session.user_id:
            return
        if await self._is_writer(session):
            return
        msg = f"the caller may not change LLM provider {provider.id}"
        raise PermissionDeniedError(msg)

    async def _can_use(self, session: SessionUser, provider: LlmProvider) -> bool:
        """Returns whether the caller may run against the given provider."""
        if provider.is_public or provider.owner_user_id == session.user_id:
            return True
        if provider.is_shared_with_user(session.user_id):
            return True
        if await self._is_writer(session):
            return True
        groups = await self._iam.effective_group_ids(session.session_id)
        return provider.is_shared_with_any_group(groups)

    def _resolve_tenant(
        self,
        session: SessionUser,
        tenant_id: UUID | None,
        is_public: bool,
    ) -> UUID | None:
        """Resolves the tenant a new provider is scoped to."""
        if tenant_id is None:
            return None if is_public else session.tenant_id
        return tenant_id

    async def _checked_default_target(
        self,
        session: SessionUser,
        scope: str,
        target_id: UUID | None,
    ) -> UUID | None:
        """Returns the target of a default pointer after checking the caller."""
        if scope == "system":
            if not await self._is_writer(session):
                msg = "only an administrator may set the system default"
                raise PermissionDeniedError(msg)
            return None
        if scope == "tenant":
            tenant_id = target_id or session.tenant_id
            if tenant_id is None:
                msg = "a tenant default needs a tenant"
                raise ValueError(msg)
            if tenant_id != session.tenant_id and not await self._is_writer(session):
                msg = f"the caller may not set the default of tenant {tenant_id}"
                raise PermissionDeniedError(msg)
            return tenant_id
        if scope != "user":
            msg = f"unknown default scope {scope!r}"
            raise ValueError(msg)
        user_id = target_id or session.user_id
        if user_id != session.user_id and not await self._is_writer(session):
            msg = f"the caller may not set the default of user {user_id}"
            raise PermissionDeniedError(msg)
        return user_id

    def _mark_default(
        self,
        provider: LlmProvider,
        scope: str,
        target_id: UUID | None,
        enabled: bool,
    ) -> None:
        """Applies one default marker on an aggregate."""
        if scope == "system":
            provider.mark_system_default(enabled)
        elif scope == "tenant" and target_id is not None:
            provider.mark_tenant_default(target_id, enabled)
        elif scope == "user" and target_id is not None:
            provider.mark_user_default(target_id, enabled)
        else:
            msg = f"unknown default scope {scope!r}"
            raise ValueError(msg)

    def _page(self, limit: int | None, offset: int) -> tuple[int, int]:
        """Clamps a requested page to the configured bounds."""
        size = self._options.default_page_size if limit is None else limit
        return max(1, min(size, self._options.max_page_size)), max(0, offset)

    async def _visible_row(self, session: SessionUser, provider_id: UUID) -> ProviderRow:
        """Returns a provider row the caller may read, or raises."""
        row = await self._view.get_provider(provider_id)
        if row is None:
            msg = f"LLM provider {provider_id} does not exist"
            raise UnknownProviderError(msg)
        if row.is_public or row.owner_user_id == session.user_id:
            return row
        shares = await self._view.list_shares(provider_id)
        groups = await self._iam.effective_group_ids(session.session_id)
        for share in shares:
            if share.scope == "user" and share.target_id == session.user_id:
                return row
            if share.scope == "group" and share.target_id in groups:
                return row
        if await self._is_writer(session):
            return row
        msg = f"LLM provider {provider_id} does not exist"
        raise UnknownProviderError(msg)

    async def _detail(self, row: ProviderRow) -> ProviderDetail:
        """Builds the detail of a provider from its shares and pointers."""
        shares: list[ProviderShareRow] = await self._view.list_shares(row.provider_id)
        defaults: list[ProviderDefaultRow] = await self._view.list_defaults(row.provider_id)
        return ProviderDetail(
            provider=row,
            shared_with_user_ids=[s.target_id for s in shares if s.scope == "user"],
            shared_with_group_ids=[s.target_id for s in shares if s.scope == "group"],
            default_for_tenant_ids=[d.target_id for d in defaults if d.scope == "tenant"],
            default_for_user_ids=[d.target_id for d in defaults if d.scope == "user"],
        )
