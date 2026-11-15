"""Prerequisites of the HTTP clients behind the provider adapters."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import httpx2
import pytest


@pytest.mark.parametrize(
    "transport_factory",
    [httpx.HTTPTransport, httpx2.HTTPTransport],
    ids=["httpx", "httpx2"],
)
def test_a_socks_proxy_can_be_built(transport_factory: Callable[..., object]) -> None:
    """A SOCKS proxy in the environment must not break an agent run.

    Container images and shells commonly export ``ALL_PROXY=socks5://…``, and
    httpx reads it for every outbound request — including the one the OpenAI SDK
    makes. Without the ``socksio`` shim that request fails with "install
    httpx[socks]", which surfaces in the chat as a run error before a single
    token is produced.
    """
    transport = transport_factory(proxy="socks5://127.0.0.1:1080")

    assert transport is not None
