"""User-typed MCP / A2A / discovery URLs must not reach metadata, loopback or other pods."""
import asyncio

import pytest

from global_utils.utils.net_guard import UnsafeUrlError
from mas.elements.providers.a2a_client.client import A2AClient, A2AConnectionError
from mas.elements.providers.mcp_server_client.transport.sse_transport import SseTransportManager
from mas.elements.providers.mcp_server_client.transport.streamable_http_transport import StreamableHttpTransportManager

BAD = ["http://169.254.169.254/latest/meta-data/", "http://127.0.0.1:6379/", "http://localhost:8080/", "http://10.0.0.5/"]


@pytest.mark.parametrize("url", BAD)
def test_a2a_client_refuses_to_connect(url):
    async def go():
        async with A2AClient(base_url=url):
            pass

    with pytest.raises(A2AConnectionError, match="Failed to connect"):
        asyncio.run(go())


@pytest.mark.parametrize("url", BAD)
def test_mcp_streamable_transport_refuses(url):
    transport = StreamableHttpTransportManager(endpoint=url, headers={})

    async def go():
        async with transport._create_transport_context():
            pass

    with pytest.raises(UnsafeUrlError):
        asyncio.run(go())


@pytest.mark.parametrize("url", BAD)
def test_mcp_sse_transport_refuses(url):
    with pytest.raises(UnsafeUrlError):
        SseTransportManager(endpoint=url, headers={})._create_transport_context()


@pytest.mark.parametrize("url", BAD)
def test_oauth_discovery_get_refuses(url):
    from adapters.outbound.http.httpx_client import HttpxClient

    with pytest.raises(UnsafeUrlError):
        asyncio.run(HttpxClient().get(url))
