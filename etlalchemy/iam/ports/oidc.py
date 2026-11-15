"""OIDC client port of the IAM context.

This repository deliberately contains **no** identity-provider client: the
authorization-code redirect, the code exchange, the ID-token signature check and
the JWKS cache all belong to the host application. The host implements
:class:`OidcClient`, and the IAM core only ever sees the verified ``(issuer,
subject)`` pair:

1. the host redirects the browser to :meth:`OidcClient.authorization_url`;
2. the provider calls back to the host with a ``code``;
3. the host exchanges the code with :meth:`OidcClient.exchange`, using
   :meth:`etlalchemy.iam.application.IamApplication.provider_client_secret` for
   the client secret (resolved from ``client_secret_ref`` per call);
4. the host calls
   :meth:`etlalchemy.iam.application.IamApplication.authenticate_oidc`.

An unknown subject comes back as ``UnboundOidcIdentity``: there is no first-login
auto-registration, so the host asks the user to log in with a password (or an
administrator pre-binds the subject) and then calls ``create_oidc_identity``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # pragma: no cover
    from etlalchemy.iam.projection.view import ProviderRow


@dataclass(frozen=True)
class OidcSubject:
    """The verified identity an OIDC client extracts from a token."""

    issuer: str
    """Issuer the token was issued by, exactly as it appears in the ``iss`` claim."""
    subject: str
    """Subject identifier of the user at the issuer (the ``sub`` claim)."""
    email: str | None = None
    """Optional email claim, useful when an administrator pre-binds a subject."""
    display_name: str | None = None
    """Optional display name claim."""


class OidcClient(Protocol):
    """Protocol the host application implements to talk to an identity provider."""

    def authorization_url(
        self,
        provider: ProviderRow,
        redirect_uri: str,
        state: str,
    ) -> str:
        """Returns the URL the browser is redirected to.

        Args:
            provider: The provider the user chose; ``provider.config`` holds the
                endpoints and the requested scopes.
            redirect_uri: Callback URL registered at the provider; when the config
                lists ``redirect_uris`` it must be one of them.
            state: Opaque anti-forgery value the callback must echo back.

        Returns:
            The authorization endpoint URL with the query parameters applied.
        """
        ...

    async def exchange(
        self,
        provider: ProviderRow,
        code: str,
        redirect_uri: str,
    ) -> OidcSubject:
        """Exchanges an authorization code for the verified subject.

        The implementation is responsible for validating the ID token signature
        against the provider's JWKS, checking ``iss``/``aud``/``exp`` and fetching
        the userinfo endpoint when the claims it needs are not in the token.

        Args:
            provider: The provider that issued the code.
            code: The ``code`` query parameter the callback received.
            redirect_uri: The same callback URL that started the flow.

        Returns:
            The verified issuer and subject.

        Raises:
            LookupError: When the token cannot be exchanged or verified.
        """
        ...


__all__ = ["OidcClient", "OidcSubject"]
