"""IAM aggregates: tenants, users, identities, sessions, groups and providers."""

from etlalchemy.iam.aggregates.auth_provider import AuthProvider
from etlalchemy.iam.aggregates.group import Group
from etlalchemy.iam.aggregates.identity import Identity
from etlalchemy.iam.aggregates.session import Session
from etlalchemy.iam.aggregates.tenant import Tenant
from etlalchemy.iam.aggregates.types import (
    ApiKey,
    GroupMember,
    IdentityRef,
    Membership,
    OidcConfig,
    Permission,
    TenantMembership,
)
from etlalchemy.iam.aggregates.user import User

__all__ = [
    "ApiKey",
    "AuthProvider",
    "Group",
    "GroupMember",
    "Identity",
    "IdentityRef",
    "Membership",
    "OidcConfig",
    "Permission",
    "Session",
    "Tenant",
    "TenantMembership",
    "User",
]
