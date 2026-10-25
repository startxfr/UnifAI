"""Where may the server connect to on behalf of a user?

A URL typed by a person (an MCP server, an A2A agent, an OAuth discovery document, a Confluence
site) is fetched by *our* server, from inside the cluster. Without a check that is a way to reach
what the person cannot: the cloud metadata service, other pods, loopback services, the Kubernetes API.

The rule (:func:`check_outbound_url`):

* the scheme is http or https, with no credentials in the URL;
* a host that resolves to a public address is allowed;
* a host that resolves to a loopback, link-local (including 169.254.169.254), unspecified,
  multicast, reserved or private address is refused, unless its name is on the allow-list:
  the platform's own runtime namespace (``*.zuno-ai-run.svc``) and the names listed in
  ``OUTBOUND_ALLOWED_HOSTS`` (comma-separated, exact host or ``.suffix``).

:func:`check_outbound_url` alone resolves the name before the connection, so a name that answers
differently a moment later (DNS rebinding) is not caught. The HTTP clients that carry a user-typed URL
therefore use :mod:`global_utils.utils.net_guard_httpx` (or ``net_guard_requests``): they run
:func:`vet_outbound_url` on every request, redirect hops included, and connect to the address that was
just checked. This is still a guard against mistakes and probing, not a network policy.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Callable, Iterable
from urllib.parse import urlparse

ALLOWED_HOSTS_ENV = "OUTBOUND_ALLOWED_HOSTS"
# The platform's own runtime namespace: its gateways and model servers are legitimate targets.
DEFAULT_ALLOWED_SUFFIXES = (".zuno-ai-run.svc", ".zuno-ai-run.svc.cluster.local")

Resolver = Callable[[str], Iterable[str]]


class UnsafeUrlError(ValueError):
    """The URL points somewhere a user-supplied URL must not reach."""


def _resolve(host: str) -> list[str]:
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)})
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"the host '{host}' cannot be resolved") from exc


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _allowed_by_name(host: str, extra: Iterable[str] | None) -> bool:
    entries = list(DEFAULT_ALLOWED_SUFFIXES)
    entries += [e.strip().lower() for e in (extra if extra is not None else os.environ.get(ALLOWED_HOSTS_ENV, "").split(",")) if e and e.strip()]
    return any(host == e or (e.startswith(".") and host.endswith(e)) for e in entries)


def vet_outbound_url(
    url: str,
    *,
    allowed_hosts: Iterable[str] | None = None,
    resolver: Resolver | None = None,
) -> tuple[str, list[str] | None]:
    """Check ``url`` and return ``(host, addresses)``.

    ``addresses`` are the public addresses the host resolved to, in the order to try them; ``None`` when
    the host is trusted by name (the platform's runtime namespace or the allow-list), in which case the
    caller connects the usual way. Raises :class:`UnsafeUrlError` when the URL must not be reached.
    """
    try:
        parts = urlparse((url or "").strip())
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError as exc:
        raise UnsafeUrlError("the URL is malformed") from exc
    if parts.scheme not in ("http", "https") or not host:
        raise UnsafeUrlError("the URL must be an http(s) URL with a host")
    if parts.username or parts.password:
        raise UnsafeUrlError("the URL must not carry credentials")
    del port
    if host == "localhost" or host.endswith(".localhost"):
        raise UnsafeUrlError("loopback hosts are not reachable from here")

    if _allowed_by_name(host, allowed_hosts):
        return host, None
    try:
        literal = ipaddress.ip_address(host)
        addresses = [str(literal)]
    except ValueError:
        addresses = list((resolver or _resolve)(host))
    if not addresses:
        raise UnsafeUrlError(f"the host '{host}' cannot be resolved")
    for address in addresses:
        if not _is_public(address):
            raise UnsafeUrlError(f"the host '{host}' resolves to a non-public address; it is not reachable from here")
    return host, addresses


def check_outbound_url(
    url: str,
    *,
    allowed_hosts: Iterable[str] | None = None,
    resolver: Resolver | None = None,
) -> str:
    """Return ``url`` when the server may connect to it, else raise :class:`UnsafeUrlError`."""
    vet_outbound_url(url, allowed_hosts=allowed_hosts, resolver=resolver)
    return url
