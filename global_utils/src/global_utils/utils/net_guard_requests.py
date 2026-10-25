"""``requests`` adapter that applies the outbound-URL guard to every request, redirect hops included.

``requests`` calls ``HTTPAdapter.send`` once per hop, so mounting this adapter on a session vets each
URL the session is about to fetch just before the connection. The address is not pinned (``requests``
offers no clean hook for it); the window between the check and the connection is the one left by
:func:`~global_utils.utils.net_guard.check_outbound_url`.
"""
from __future__ import annotations

from collections.abc import Iterable

from requests.adapters import HTTPAdapter

from global_utils.utils.net_guard import Resolver, UnsafeUrlError, check_outbound_url


class GuardedAdapter(HTTPAdapter):
    def __init__(self, *args, allowed_hosts: Iterable[str] | None = None, resolver: Resolver | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._allowed_hosts = list(allowed_hosts) if allowed_hosts is not None else None
        self._resolver = resolver

    def send(self, request, **kwargs):  # noqa: D401 - requests API
        check_outbound_url(request.url, allowed_hosts=self._allowed_hosts, resolver=self._resolver)
        return super().send(request, **kwargs)


def guard_session(session, *, allowed_hosts: Iterable[str] | None = None):
    """Mount the guard on both schemes of ``session`` and return it."""
    adapter = GuardedAdapter(allowed_hosts=allowed_hosts)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


__all__ = ["GuardedAdapter", "UnsafeUrlError", "guard_session"]
