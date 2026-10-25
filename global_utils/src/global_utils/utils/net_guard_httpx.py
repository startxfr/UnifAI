"""httpx transport that applies the outbound-URL guard to every request and pins the connection.

Use it for any client that fetches a URL a person typed or a server answered with::

    httpx.AsyncClient(transport=GuardedAsyncTransport(), follow_redirects=False)

Every request, and every redirect hop when the client follows redirects, is vetted with
:func:`~global_utils.utils.net_guard.vet_outbound_url`. For a public host the connection goes to the
address that was just vetted, with the original name kept for the ``Host`` header and for TLS
(SNI and certificate check), so the name cannot resolve to something else between the check and the
connection (DNS rebinding). Hosts trusted by name (the platform's runtime namespace, the allow-list)
connect the usual way.
"""
from __future__ import annotations

from collections.abc import Iterable

import httpx

from global_utils.utils.net_guard import Resolver, UnsafeUrlError, vet_outbound_url


def _pin(request: httpx.Request, host: str, addresses: list[str]) -> None:
    address = addresses[0]
    request.headers["Host"] = request.url.netloc.decode("ascii")
    request.url = request.url.copy_with(host=address)
    if request.url.scheme == "https":
        request.extensions = {**request.extensions, "sni_hostname": host}


class GuardedAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        *,
        allowed_hosts: Iterable[str] | None = None,
        resolver: Resolver | None = None,
        inner: httpx.AsyncBaseTransport | None = None,
        **transport_kwargs,
    ) -> None:
        self._allowed_hosts = list(allowed_hosts) if allowed_hosts is not None else None
        self._resolver = resolver
        self._inner = inner or httpx.AsyncHTTPTransport(**transport_kwargs)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host, addresses = vet_outbound_url(str(request.url), allowed_hosts=self._allowed_hosts, resolver=self._resolver)
        if addresses is not None:
            _pin(request, host, addresses)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


class GuardedTransport(httpx.BaseTransport):
    """The synchronous twin of :class:`GuardedAsyncTransport`."""

    def __init__(
        self,
        *,
        allowed_hosts: Iterable[str] | None = None,
        resolver: Resolver | None = None,
        inner: httpx.BaseTransport | None = None,
        **transport_kwargs,
    ) -> None:
        self._allowed_hosts = list(allowed_hosts) if allowed_hosts is not None else None
        self._resolver = resolver
        self._inner = inner or httpx.HTTPTransport(**transport_kwargs)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host, addresses = vet_outbound_url(str(request.url), allowed_hosts=self._allowed_hosts, resolver=self._resolver)
        if addresses is not None:
            _pin(request, host, addresses)
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


__all__ = ["GuardedAsyncTransport", "GuardedTransport", "UnsafeUrlError"]
