"""HTTP client factory for the MCP transports: the SDK's defaults plus the outbound-URL guard.

The SDK's own factory (``create_mcp_http_client``) builds a plain client. This one builds the same
client with :class:`GuardedAsyncTransport`, so the address of a user-typed MCP URL is vetted again
at connect time (DNS rebinding) and on every hop the transport follows within the endpoint's origin.
"""
from typing import Optional

import httpx
from mcp.shared._httpx_utils import MCP_DEFAULT_SSE_READ_TIMEOUT, MCP_DEFAULT_TIMEOUT

from global_utils.utils.net_guard_httpx import GuardedAsyncTransport


def create_guarded_mcp_http_client(
    headers: Optional[dict] = None,
    timeout: Optional[httpx.Timeout] = None,
    auth: Optional[httpx.Auth] = None,
) -> httpx.AsyncClient:
    kwargs = {
        "timeout": timeout or httpx.Timeout(MCP_DEFAULT_TIMEOUT, read=MCP_DEFAULT_SSE_READ_TIMEOUT),
        "transport": GuardedAsyncTransport(),
    }
    if headers is not None:
        kwargs["headers"] = headers
    if auth is not None:
        kwargs["auth"] = auth
    return httpx.AsyncClient(**kwargs)
