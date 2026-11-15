"""HTTP routes exposing the IAM context.

Every route except the login and bootstrap ones authenticates through
``Authorization: Bearer iam_sess_<session_id>``. The session id never travels in a
body, a query string or a path.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from eventsourcing.application import AggregateNotFoundError
from eventsourcing.persistence import RecordConflictError
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from etlalchemy.app.api.dependencies.auth import get_auth_session, get_session_id
from etlalchemy.app.auth import AuthSession, SessionAuthenticator
from etlalchemy.app.bootstrap import Container
from etlalchemy.app.config.settings import AppSettings
from etlalchemy.app.schemas.iam import (
    ApiKeyResponse,
    ApiKeySecretResponse,
    AuditResponse,
    AuthorizeResponse,
    BootstrapStatusResponse,
    GroupCreatedResponse,
    GroupMemberResponse,
    GroupResponse,
    IdentityCreatedResponse,
    IdentityResponse,
    ProviderCreatedResponse,
    ProviderResponse,
    SessionResponse,
    TenantCreatedResponse,
    TenantResponse,
    TokenResponse,
    UserCreatedResponse,
    UserResponse,
    UserSummaryResponse,
)
from etlalchemy.iam.aggregates.errors import (
    AuthenticationError,
    CredentialError,
    DiscardedError,
    IamError,
    IamValidationError,
    IdentityUnavailableError,
    PermissionDeniedError,
    SessionExpiredError,
    SessionRevokedError,
    TenantSuspendedError,
    UnknownAuthProviderError,
    UnknownGroupError,
    UnknownIdentityError,
    UnknownTenantError,
    UnknownUserError,
    UserSuspendedError,
)
from etlalchemy.iam.application import IamApplication, SessionRef

router = APIRouter(prefix="/iam", tags=["iam"])

CONFLICT_ERRORS = (IamError, RecordConflictError, DiscardedError)
UNAUTHORIZED_ERRORS = (
    AuthenticationError,
    CredentialError,
    SessionExpiredError,
    SessionRevokedError,
)
FORBIDDEN_ERRORS = (
    PermissionDeniedError,
    IdentityUnavailableError,
    TenantSuspendedError,
    UserSuspendedError,
)
NOT_FOUND_ERRORS = (
    UnknownTenantError,
    UnknownUserError,
    UnknownIdentityError,
    UnknownGroupError,
    UnknownAuthProviderError,
    AggregateNotFoundError,
)


def _error_handler(status_code: int) -> Any:
    """Builds a handler that renders the error message with the given status."""

    async def handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    return handler


def add_exception_handlers(app: FastAPI) -> None:
    """Maps IAM errors to HTTP responses."""
    for unauthorized in UNAUTHORIZED_ERRORS:
        app.add_exception_handler(unauthorized, _error_handler(401))
    for forbidden in FORBIDDEN_ERRORS:
        app.add_exception_handler(forbidden, _error_handler(403))
    for missing in NOT_FOUND_ERRORS:
        app.add_exception_handler(missing, _error_handler(404))
    app.add_exception_handler(IamValidationError, _error_handler(400))
    for conflict in CONFLICT_ERRORS:
        app.add_exception_handler(conflict, _error_handler(409))
    app.add_exception_handler(ValueError, _error_handler(400))


class PasswordLogin(BaseModel):
    """Body of ``POST /iam/auth/password``."""

    login: str
    password: str
    tenant_id: UUID | None = None


class ApiKeyLogin(BaseModel):
    """Body of ``POST /iam/auth/api-key``."""

    api_key: str


class OidcLogin(BaseModel):
    """Body of ``POST /iam/auth/oidc``."""

    issuer: str
    subject: str
    tenant_id: UUID | None = None


class AuthorizeBody(BaseModel):
    """Body of ``POST /iam/authorize``."""

    obj: str
    act: str


class TenantCreate(BaseModel):
    """Body of ``POST /iam/tenants``."""

    name: str
    description: str = ""


class TenantPatch(BaseModel):
    """Body of ``PATCH /iam/tenants/{tenant_id}``."""

    name: str | None = None
    description: str | None = None
    status: str | None = None


class TenantMemberBody(BaseModel):
    """Body of the tenant membership routes."""

    user_id: UUID


class UserCreate(BaseModel):
    """Body of ``POST /iam/users``."""

    username: str
    email: str
    display_name: str = ""


class UserPatch(BaseModel):
    """Body of ``PATCH /iam/users/{user_id}``."""

    username: str | None = None
    email: str | None = None
    display_name: str | None = None
    status: str | None = None


class PasswordIdentityCreate(BaseModel):
    """Body of ``POST /iam/users/{user_id}/identities/password``."""

    password: str


class OidcIdentityCreate(BaseModel):
    """Body of ``POST /iam/users/{user_id}/identities/oidc``."""

    provider_id: UUID
    subject: str


class IdentityPatch(BaseModel):
    """Body of ``PATCH /iam/identities/{identity_id}``."""

    display_name: str | None = None
    status: str | None = None


class PasswordChange(BaseModel):
    """Body of ``POST /iam/passwords/change``."""

    old_password: str
    new_password: str


class PasswordReset(BaseModel):
    """Body of ``POST /iam/passwords/reset``."""

    login: str
    new_password: str


class ApiKeyCreate(BaseModel):
    """Body of ``POST /iam/users/{user_id}/api-keys``."""

    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None


class ApiKeyRotate(BaseModel):
    """Body of ``POST /iam/users/{user_id}/api-keys/{key_id}/rotate``."""

    grace_days: int = 1


class GroupCreate(BaseModel):
    """Body of ``POST /iam/tenants/{tenant_id}/groups``."""

    name: str
    parent_group_id: UUID | None = None
    description: str = ""


class GroupPatch(BaseModel):
    """Body of ``PATCH /iam/groups/{group_id}``."""

    name: str | None = None
    description: str | None = None


class GroupParentBody(BaseModel):
    """Body of ``POST /iam/groups/{group_id}/parent``."""

    new_parent_id: UUID | None = None


class GroupMemberBody(BaseModel):
    """Body of ``POST /iam/groups/{group_id}/members``."""

    member_id: UUID
    member_kind: str | None = None


class PermissionBody(BaseModel):
    """Body of the group permission routes."""

    obj: str
    act: str


class ProviderCreate(BaseModel):
    """Body of ``POST /iam/providers``."""

    provider_key: str
    display_name: str
    config: dict[str, str]
    kind: str = "OIDC"
    tenant_id: UUID | None = None


class ProviderPatch(BaseModel):
    """Body of ``PATCH /iam/providers/{provider_id}``."""

    display_name: str | None = None
    status: str | None = None
    config: dict[str, str] | None = None


def _session_response(
    ref: SessionRef,
    access_token: str,
    lead_minutes: int,
) -> SessionResponse:
    """Renders a session reference and the bearer token that addresses it."""
    return SessionResponse(
        access_token=access_token,
        session_id=ref.session_id,
        identity_id=ref.identity_id,
        user_id=ref.user_id,
        tenant_id=ref.tenant_id,
        expires_at=ref.expires_at,
        refresh_at=ref.expires_at - timedelta(minutes=lead_minutes),
    )


def _parse_tenant_scope(scopes: list[str]) -> UUID | None:
    """Reads the ``tenant:<uuid>`` entry out of the OAuth2 scope list.

    A login form cannot carry extra fields, so the tenant travels as a scope token.
    Every other token is ignored: the form scope never influences authorization.

    Args:
        scopes: Scope tokens submitted by the client.

    Returns:
        The tenant id, or ``None`` when the form asked for a global session.

    Raises:
        HTTPException: 400 when the entry after ``tenant:`` is not a UUID.
    """
    for scope in scopes:
        if not scope.startswith("tenant:"):
            continue
        try:
            return UUID(scope.removeprefix("tenant:"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid tenant scope") from exc
    return None


# -- authentication ---------------------------------------------------------


@router.post("/auth/token", response_model=TokenResponse)
@inject
async def login_token(
    form: OAuth2PasswordRequestForm = Depends(),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
    authenticator: SessionAuthenticator = Depends(  # noqa: B008
        Provide[Container.session_authenticator]
    ),
    settings: AppSettings = Depends(Provide[Container.settings]),  # noqa: B008
) -> TokenResponse:
    """Authenticates with the OAuth2 password grant form used by Swagger UI."""
    ref = await application.authenticate_password(
        form.username,
        form.password,
        _parse_tenant_scope(form.scopes),
    )
    lead = settings.iam.session_refresh_lead_minutes
    return TokenResponse(
        access_token=authenticator.format_token(ref.session_id),
        expires_at=ref.expires_at,
        refresh_at=ref.expires_at - timedelta(minutes=lead),
        session_id=ref.session_id,
        user_id=ref.user_id,
        identity_id=ref.identity_id,
        tenant_id=ref.tenant_id,
    )


@router.post("/auth/password", response_model=SessionResponse)
@inject
async def login_password(
    body: PasswordLogin,
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
    authenticator: SessionAuthenticator = Depends(  # noqa: B008
        Provide[Container.session_authenticator]
    ),
    settings: AppSettings = Depends(Provide[Container.settings]),  # noqa: B008
) -> SessionResponse:
    """Authenticates a login and password."""
    ref = await application.authenticate_password(body.login, body.password, body.tenant_id)
    lead = settings.iam.session_refresh_lead_minutes
    return _session_response(ref, authenticator.format_token(ref.session_id), lead)


@router.post("/auth/api-key", response_model=SessionResponse)
@inject
async def login_api_key(
    body: ApiKeyLogin,
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
    authenticator: SessionAuthenticator = Depends(  # noqa: B008
        Provide[Container.session_authenticator]
    ),
    settings: AppSettings = Depends(Provide[Container.settings]),  # noqa: B008
) -> SessionResponse:
    """Authenticates a raw API key."""
    ref = await application.authenticate_api_key(body.api_key)
    lead = settings.iam.session_refresh_lead_minutes
    return _session_response(ref, authenticator.format_token(ref.session_id), lead)


@router.post("/auth/oidc", response_model=SessionResponse)
@inject
async def login_oidc(
    body: OidcLogin,
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
    authenticator: SessionAuthenticator = Depends(  # noqa: B008
        Provide[Container.session_authenticator]
    ),
    settings: AppSettings = Depends(Provide[Container.settings]),  # noqa: B008
) -> SessionResponse:
    """Maps an OIDC subject to an identity and issues a session."""
    result = await application.authenticate_oidc(body.issuer, body.subject, body.tenant_id)
    if not isinstance(result, SessionRef):
        raise AuthenticationError(f"the subject is not bound: {result.issuer}")
    lead = settings.iam.session_refresh_lead_minutes
    return _session_response(result, authenticator.format_token(result.session_id), lead)


@router.post("/auth/refresh", response_model=SessionResponse)
@inject
async def refresh_session(
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
    authenticator: SessionAuthenticator = Depends(  # noqa: B008
        Provide[Container.session_authenticator]
    ),
    settings: AppSettings = Depends(Provide[Container.settings]),  # noqa: B008
) -> SessionResponse:
    """Extends the session behind the bearer token."""
    ref = await application.refresh_session(session_id)
    lead = settings.iam.session_refresh_lead_minutes
    return _session_response(ref, authenticator.format_token(ref.session_id), lead)


@router.post("/auth/logout", status_code=204)
@inject
async def logout(
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> Response:
    """Revokes the session behind the bearer token."""
    await application.revoke_session(session_id, "logout")
    return Response(status_code=204)


@router.get("/sessions/current", response_model=SessionResponse)
@inject
async def get_current_session(
    auth: AuthSession = Depends(get_auth_session),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
    authenticator: SessionAuthenticator = Depends(  # noqa: B008
        Provide[Container.session_authenticator]
    ),
    settings: AppSettings = Depends(Provide[Container.settings]),  # noqa: B008
) -> SessionResponse:
    """Returns the current state of the session behind the bearer token."""
    ref = await application.get_session(auth.session_id)
    lead = settings.iam.session_refresh_lead_minutes
    return _session_response(ref, authenticator.format_token(ref.session_id), lead)


@router.get("/bootstrap", response_model=BootstrapStatusResponse)
@inject
async def bootstrap_status(
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> BootstrapStatusResponse:
    """Returns whether the system already has a system administrator."""
    return BootstrapStatusResponse(completed=await application.bootstrap_status())


@router.post("/authorize", response_model=AuthorizeResponse)
@inject
async def authorize(
    body: AuthorizeBody,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> AuthorizeResponse:
    """Checks whether the authenticated caller may act on an object."""
    return AuthorizeResponse(allowed=await application.authorize(session_id, body.obj, body.act))


# -- tenants ----------------------------------------------------------------


@router.post("/tenants", status_code=201, response_model=TenantCreatedResponse)
@inject
async def create_tenant(
    body: TenantCreate,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> TenantCreatedResponse:
    """Creates a tenant."""
    tenant_id = await application.create_tenant(session_id, body.name, body.description)
    return TenantCreatedResponse(tenant_id=tenant_id)


@router.get("/tenants", response_model=list[TenantResponse])
@inject
async def list_tenants(
    _session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> list[TenantResponse]:
    """Returns every live tenant."""
    return [TenantResponse.from_row(row) for row in await application.list_tenants()]


@router.patch("/tenants/{tenant_id}", status_code=204)
@inject
async def change_tenant(
    tenant_id: UUID,
    body: TenantPatch,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> Response:
    """Changes a tenant."""
    await application.change_tenant(
        session_id,
        tenant_id,
        body.name,
        body.description,
        body.status,
    )
    return Response(status_code=204)


@router.delete("/tenants/{tenant_id}", status_code=204)
@inject
async def discard_tenant(
    tenant_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> Response:
    """Discards a tenant."""
    await application.discard_tenant(session_id, tenant_id)
    return Response(status_code=204)


@router.get("/tenants/{tenant_id}/members", response_model=list[UserResponse])
@inject
async def list_tenant_members(
    tenant_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> list[UserResponse]:
    """Returns the members of a tenant."""
    rows = await application.list_tenant_members(session_id, tenant_id)
    return [UserResponse.from_row(row) for row in rows]


@router.post("/tenants/{tenant_id}/members", status_code=204)
@inject
async def add_tenant_member(
    tenant_id: UUID,
    body: TenantMemberBody,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> Response:
    """Adds a user to a tenant."""
    await application.add_tenant_member(session_id, tenant_id, body.user_id)
    return Response(status_code=204)


@router.delete("/tenants/{tenant_id}/members/{user_id}", status_code=204)
@inject
async def remove_tenant_member(
    tenant_id: UUID,
    user_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> Response:
    """Removes a user from a tenant."""
    await application.remove_tenant_member(session_id, tenant_id, user_id)
    return Response(status_code=204)


# -- users ------------------------------------------------------------------


@router.post("/users", status_code=201, response_model=UserCreatedResponse)
@inject
async def create_user(
    body: UserCreate,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> UserCreatedResponse:
    """Creates a user."""
    user_id = await application.create_user(
        session_id,
        body.username,
        body.email,
        body.display_name,
    )
    return UserCreatedResponse(user_id=user_id)


@router.get("/users", response_model=list[UserResponse])
@inject
async def list_users(
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> list[UserResponse]:
    """Returns every live user."""
    rows = await application.list_users(session_id)
    return [UserResponse.from_row(row) for row in rows]


@router.get("/users/search", response_model=list[UserSummaryResponse])
@inject
async def search_users(
    term: Annotated[str, Query()] = "",
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> list[UserSummaryResponse]:
    """Suggests users for an ``@`` mention; any signed-in user may call it.

    ``term`` is optional: an empty term answers the first users, which is what a
    bare ``@`` shows before anything is typed.
    """
    rows = await application.search_users(session_id, term, limit)
    return [UserSummaryResponse.from_row(row) for row in rows]


@router.get("/users/{user_id}", response_model=UserResponse)
@inject
async def get_user(
    user_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> UserResponse:
    """Returns one user."""
    return UserResponse.from_row(await application.get_user(session_id, user_id))


@router.patch("/users/{user_id}", status_code=204)
@inject
async def change_user(
    user_id: UUID,
    body: UserPatch,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> Response:
    """Changes a user."""
    await application.change_user(
        session_id,
        user_id,
        body.username,
        body.email,
        body.display_name,
        body.status,
    )
    return Response(status_code=204)


@router.delete("/users/{user_id}", status_code=204)
@inject
async def discard_user(
    user_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> Response:
    """Discards a user."""
    await application.discard_user(session_id, user_id)
    return Response(status_code=204)


@router.post("/users/{user_id}/system-admin", status_code=204)
@inject
async def grant_system_admin(
    user_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> Response:
    """Grants the system administrator flag."""
    await application.grant_system_admin(session_id, user_id)
    return Response(status_code=204)


@router.delete("/users/{user_id}/system-admin", status_code=204)
@inject
async def revoke_system_admin(
    user_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> Response:
    """Revokes the system administrator flag."""
    await application.revoke_system_admin(session_id, user_id)
    return Response(status_code=204)


# -- identities and credentials ---------------------------------------------


@router.post(
    "/users/{user_id}/identities/password",
    status_code=201,
    response_model=IdentityCreatedResponse,
)
@inject
async def create_password_identity(
    user_id: UUID,
    body: PasswordIdentityCreate,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> IdentityCreatedResponse:
    """Creates the password identity of a user."""
    identity_id = await application.create_password_identity(
        session_id,
        user_id,
        body.password,
    )
    return IdentityCreatedResponse(identity_id=identity_id)


@router.post(
    "/users/{user_id}/identities/oidc",
    status_code=201,
    response_model=IdentityCreatedResponse,
)
@inject
async def create_oidc_identity(
    user_id: UUID,
    body: OidcIdentityCreate,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> IdentityCreatedResponse:
    """Creates an OIDC identity bound to a provider and subject."""
    identity_id = await application.create_oidc_identity(
        session_id,
        user_id,
        body.provider_id,
        body.subject,
    )
    return IdentityCreatedResponse(identity_id=identity_id)


@router.get("/users/{user_id}/identities", response_model=list[IdentityResponse])
@inject
async def list_identities(
    user_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> list[IdentityResponse]:
    """Returns the identities of a user."""
    rows = await application.list_identities(session_id, user_id)
    return [IdentityResponse.from_row(row) for row in rows]


@router.patch("/identities/{identity_id}", status_code=204)
@inject
async def change_identity(
    identity_id: UUID,
    body: IdentityPatch,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> Response:
    """Changes the display name or status of an identity."""
    await application.change_identity(
        session_id,
        identity_id,
        body.display_name,
        body.status,
    )
    return Response(status_code=204)


@router.delete("/identities/{identity_id}", status_code=204)
@inject
async def discard_identity(
    identity_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> Response:
    """Discards an identity."""
    await application.discard_identity(session_id, identity_id)
    return Response(status_code=204)


@router.post("/passwords/change", status_code=204)
@inject
async def change_own_password(
    body: PasswordChange,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> Response:
    """Changes the password of the identity behind the bearer token."""
    await application.change_own_password(
        session_id,
        body.old_password,
        body.new_password,
    )
    return Response(status_code=204)


@router.post("/passwords/reset", status_code=204)
@inject
async def reset_password(
    body: PasswordReset,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> Response:
    """Resets the password of a user without the current password."""
    await application.change_user_password_via_admin(
        session_id,
        body.login,
        body.new_password,
    )
    return Response(status_code=204)


# -- API keys ---------------------------------------------------------------


@router.post(
    "/users/{user_id}/api-keys",
    status_code=201,
    response_model=ApiKeySecretResponse,
)
@inject
async def create_api_key(
    user_id: UUID,
    body: ApiKeyCreate,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> ApiKeySecretResponse:
    """Creates an API key and returns its secret once."""
    created = await application.create_api_key(
        session_id,
        user_id,
        body.scopes,
        body.expires_at,
    )
    return ApiKeySecretResponse(key_id=created.key_id, secret=created.secret)


@router.get("/users/{user_id}/api-keys", response_model=list[ApiKeyResponse])
@inject
async def list_api_keys(
    user_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> list[ApiKeyResponse]:
    """Returns the API keys of a user."""
    rows = await application.list_api_keys(session_id, user_id)
    return [ApiKeyResponse.from_row(row) for row in rows]


@router.post(
    "/users/{user_id}/api-keys/{key_id}/rotate",
    status_code=201,
    response_model=ApiKeySecretResponse,
)
@inject
async def rotate_api_key(
    user_id: UUID,
    key_id: UUID,
    body: ApiKeyRotate,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> ApiKeySecretResponse:
    """Rotates an API key and returns the new secret once."""
    created = await application.rotate_api_key(
        session_id,
        user_id,
        key_id,
        timedelta(days=body.grace_days),
    )
    return ApiKeySecretResponse(key_id=created.key_id, secret=created.secret)


@router.delete("/users/{user_id}/api-keys/{key_id}", status_code=204)
@inject
async def revoke_api_key(
    user_id: UUID,
    key_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> Response:
    """Revokes an API key."""
    await application.revoke_api_key(session_id, user_id, key_id)
    return Response(status_code=204)


# -- groups -----------------------------------------------------------------


@router.post(
    "/tenants/{tenant_id}/groups",
    status_code=201,
    response_model=GroupCreatedResponse,
)
@inject
async def create_group(
    tenant_id: UUID,
    body: GroupCreate,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> GroupCreatedResponse:
    """Creates a group in a tenant."""
    group_id = await application.create_group(
        session_id,
        tenant_id,
        body.name,
        body.parent_group_id,
        body.description,
    )
    return GroupCreatedResponse(group_id=group_id)


@router.get("/tenants/{tenant_id}/groups", response_model=list[GroupResponse])
@inject
async def list_groups(
    tenant_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> list[GroupResponse]:
    """Returns the groups of a tenant."""
    rows = await application.list_groups(session_id, tenant_id)
    return [GroupResponse.from_row(row) for row in rows]


@router.patch("/groups/{group_id}", status_code=204)
@inject
async def change_group(
    group_id: UUID,
    body: GroupPatch,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> Response:
    """Changes a group."""
    await application.change_group(session_id, group_id, body.name, body.description)
    return Response(status_code=204)


@router.post("/groups/{group_id}/parent", status_code=204)
@inject
async def set_group_parent(
    group_id: UUID,
    body: GroupParentBody,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> Response:
    """Moves a group below another group."""
    await application.set_group_parent(session_id, group_id, body.new_parent_id)
    return Response(status_code=204)


@router.delete("/groups/{group_id}", status_code=204)
@inject
async def discard_group(
    group_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> Response:
    """Discards a group and its subtree."""
    await application.discard_group(session_id, group_id)
    return Response(status_code=204)


@router.get("/groups/{group_id}/members", response_model=list[GroupMemberResponse])
@inject
async def list_group_members(
    group_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    recursive: bool = False,
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> list[GroupMemberResponse]:
    """Returns the members of a group."""
    rows = await application.list_group_members(session_id, group_id, recursive)
    return [GroupMemberResponse.from_row(row) for row in rows]


@router.post("/groups/{group_id}/members", status_code=204)
@inject
async def add_group_member(
    group_id: UUID,
    body: GroupMemberBody,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> Response:
    """Adds a user or a child group to a group."""
    await application.add_group_member(
        session_id,
        group_id,
        body.member_id,
        body.member_kind,
    )
    return Response(status_code=204)


@router.delete("/groups/{group_id}/members/{member_id}", status_code=204)
@inject
async def remove_group_member(
    group_id: UUID,
    member_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> Response:
    """Removes a member from a group."""
    await application.remove_group_member(session_id, group_id, member_id)
    return Response(status_code=204)


@router.post("/tenants/{tenant_id}/groups/{group_id}/permissions", status_code=204)
@inject
async def grant_group_permission(
    tenant_id: UUID,
    group_id: UUID,
    body: PermissionBody,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> Response:
    """Grants a permission to a group."""
    await application.grant_group_permission(
        session_id,
        tenant_id,
        group_id,
        body.obj,
        body.act,
    )
    return Response(status_code=204)


@router.delete("/tenants/{tenant_id}/groups/{group_id}/permissions", status_code=204)
@inject
async def revoke_group_permission(
    tenant_id: UUID,
    group_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    obj: str = Query(...),
    act: str = Query(...),
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> Response:
    """Revokes a permission from a group."""
    await application.revoke_group_permission(session_id, tenant_id, group_id, obj, act)
    return Response(status_code=204)


# -- auth providers and audit -----------------------------------------------


@router.post("/providers", status_code=201, response_model=ProviderCreatedResponse)
@inject
async def create_auth_provider(
    body: ProviderCreate,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> ProviderCreatedResponse:
    """Creates an auth provider."""
    provider_id = await application.create_auth_provider(
        session_id,
        body.provider_key,
        body.kind,
        body.display_name,
        body.config,
        body.tenant_id,
    )
    return ProviderCreatedResponse(provider_id=provider_id)


@router.get("/providers", response_model=list[ProviderResponse])
@inject
async def list_auth_providers(
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> list[ProviderResponse]:
    """Returns every live auth provider."""
    rows = await application.list_auth_providers(session_id)
    return [ProviderResponse.from_row(row) for row in rows]


@router.patch("/providers/{provider_id}", status_code=204)
@inject
async def change_auth_provider(
    provider_id: UUID,
    body: ProviderPatch,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> Response:
    """Changes an auth provider, including its configuration."""
    if body.config is not None:
        await application.update_auth_provider_config(
            session_id,
            provider_id,
            body.config,
        )
    if body.display_name is not None or body.status is not None:
        await application.change_auth_provider(
            session_id,
            provider_id,
            body.display_name,
            body.status,
        )
    return Response(status_code=204)


@router.delete("/providers/{provider_id}", status_code=204)
@inject
async def discard_auth_provider(
    provider_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    force: bool = False,
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> Response:
    """Discards an auth provider."""
    await application.discard_auth_provider(session_id, provider_id, force)
    return Response(status_code=204)


@router.get("/audit", response_model=list[AuditResponse])
@inject
async def list_audit_events(
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
    application: IamApplication = Depends(Provide[Container.iam_application]),  # noqa: B008
) -> list[AuditResponse]:
    """Returns audit records, newest first."""
    rows = await application.list_audit_events(session_id, limit, offset, action)
    return [AuditResponse.from_row(row) for row in rows]
