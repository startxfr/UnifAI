"""``requests`` adapter that applies the outbound-URL guard to every request, redirect hops included.

``requests`` calls ``HTTPAdapter.send`` once per hop, so mounting this adapter on a session vets each
URL the session is about to fetch just before the connection. With ``pin=True`` (the default) the
connection also goes to the address that was just vetted, keeping the original name for the ``Host``
header and for TLS (SNI and certificate check), so the name cannot resolve to something else between
the check and the connection (DNS rebinding). Hosts trusted by name connect the usual way. Pinning
needs ``requests`` >= 2.32 (``build_connection_pool_key_attributes``); older versions only vet.
"""
from __future__ import annotations

import threading
from collections.abc import Iterable
from urllib.parse import urlparse

from requests.adapters import HTTPAdapter

from global_utils.utils.net_guard import Resolver, UnsafeUrlError, vet_outbound_url


class GuardedAdapter(HTTPAdapter):
    def __init__(
        self,
        *args,
        allowed_hosts: Iterable[str] | None = None,
        resolver: Resolver | None = None,
        pin: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._allowed_hosts = list(allowed_hosts) if allowed_hosts is not None else None
        self._resolver = resolver
        self._pin = pin and hasattr(HTTPAdapter, "build_connection_pool_key_attributes")
        self._local = threading.local()

    def send(self, request, **kwargs):  # noqa: D401 - requests API
        host, addresses = vet_outbound_url(request.url, allowed_hosts=self._allowed_hosts, resolver=self._resolver)
        self._local.target = (host, addresses[0]) if (self._pin and addresses) else None
        if self._local.target:
            request.headers["Host"] = urlparse(request.url).netloc
        return super().send(request, **kwargs)

    def build_connection_pool_key_attributes(self, request, verify, cert=None):
        host_params, pool_kwargs = super().build_connection_pool_key_attributes(request, verify, cert)
        target = getattr(self._local, "target", None)
        if target:
            name, address = target
            host_params = {**host_params, "host": address}
            pool_kwargs = {**pool_kwargs, "server_hostname": name, "assert_hostname": name}
        return host_params, pool_kwargs


def guard_session(session, *, allowed_hosts: Iterable[str] | None = None, pin: bool = True):
    """Mount the guard on both schemes of ``session`` and return it."""
    adapter = GuardedAdapter(allowed_hosts=allowed_hosts, pin=pin)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


__all__ = ["GuardedAdapter", "UnsafeUrlError", "guard_session"]
