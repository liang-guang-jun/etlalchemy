"""Errors shared by the IAM aggregates and use cases.

Every error subclasses :class:`IamError` so the delivery layers can map one base
type. Authentication and authorization failures never reveal whether a user, an
identity or a rule exists.
"""


class IamError(Exception):
    """Base class for errors raised by the IAM context."""


class IamValidationError(IamError):
    """Raised when a command carries a field that violates the domain rules."""


class AuthenticationError(IamError):
    """Raised when authentication fails, without revealing the reason."""


class PermissionDeniedError(IamError):
    """Raised when an authorization check fails."""


class BootstrapAlreadyCompletedError(IamError):
    """Raised when bootstrap runs although a system administrator exists."""


class LastSystemAdminError(IamError):
    """Raised when the last system administrator would be removed."""


class DuplicateTenantError(IamError):
    """Raised when a tenant name is already used by a live tenant."""


class UnknownTenantError(IamError):
    """Raised when a tenant does not exist."""


class TenantSuspendedError(IamError):
    """Raised when a command targets a suspended tenant."""


class DuplicateUserError(IamError):
    """Raised when a username is already used by a live user."""


class DuplicateEmailError(IamError):
    """Raised when an email is already used by a live user."""


class UnknownUserError(IamError):
    """Raised when a user does not exist."""


class UserSuspendedError(IamError):
    """Raised when a command targets a suspended user."""


class DuplicateMembershipError(IamError):
    """Raised when a user is already an active member of the tenant."""


class UnknownMembershipError(IamError):
    """Raised when a user is not an active member of the tenant."""


class DuplicateIdentityError(IamError):
    """Raised when a user already has an identity of the same kind."""


class UnknownIdentityError(IamError):
    """Raised when an identity does not exist."""


class DuplicateOidcBindingError(IamError):
    """Raised when a subject of an issuer is already bound to another identity."""


class IdentityInvariantError(IamError):
    """Raised when an identity command does not match the identity type."""


class IdentityUnavailableError(IamError):
    """Raised when an identity cannot be used to log in."""


class LastLoginIdentityError(IamError):
    """Raised when the last usable login identity would be removed."""


class CredentialError(IamError):
    """Raised when a credential does not verify."""


class ScopeExceedsGrantError(IamError):
    """Raised when API key scopes exceed the permissions of the user."""


class DuplicateGroupError(IamError):
    """Raised when a group name is already used under the same parent."""


class UnknownGroupError(IamError):
    """Raised when a group does not exist."""


class GroupCycleError(IamError):
    """Raised when a move or membership would create a cycle."""


class GroupDepthExceededError(IamError):
    """Raised when the ancestor chain of a group is longer than allowed."""


class DuplicateGroupMemberError(IamError):
    """Raised when a member is already part of the group."""


class UnknownGroupMemberError(IamError):
    """Raised when a member is not part of the group."""


class DuplicatePermissionGrantError(IamError):
    """Raised when a group already holds the same permission."""


class UnknownPermissionGrantError(IamError):
    """Raised when a group does not hold the permission."""


class DuplicateAuthProviderError(IamError):
    """Raised when an auth provider key is already used."""


class UnknownAuthProviderError(IamError):
    """Raised when an auth provider does not exist."""


class InvalidProviderConfigError(IamError):
    """Raised when an auth provider configuration is not valid for its kind."""


class ProviderInUseError(IamError):
    """Raised when an auth provider is still referenced by an identity."""


class SessionExpiredError(IamError):
    """Raised when a session is past its expiry."""


class SessionRevokedError(IamError):
    """Raised when a session was revoked."""


class DiscardedError(IamError, RuntimeError):
    """Raised when a command targets an aggregate that was discarded."""
