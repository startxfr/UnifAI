"""The guarded clients against real MCP and A2A servers over a socket (ADR-0583, outbound guard).

The unit tests of the guard use a stand-in transport. These cross a real socket: the MCP and A2A clients the
platform uses talk to a real server through the guarded transport, the connection goes to the address the guard
vetted while the server still sees the original host name, and a name that starts answering privately after
the first connection is refused on the next request.
"""
import asyncio

import httpx
import pytest
from a2a.types import Message, Part, Role, TextPart

from global_utils.utils import net_guard
from global_utils.utils.net_guard import UnsafeUrlError
from mas.elements.providers.a2a_client.client import A2AClient
from mas.elements.providers.mcp_server_client.transport.guarded_http import create_guarded_mcp_http_client
from mas.elements.providers.mcp_server_client.transport.streamable_http_transport import StreamableHttpTransportManager

from .fixture import FIXTURE_HOST, running_servers


@pytest.fixture
def servers():
    with running_servers() as value:
        yield value


@pytest.fixture
def dns(monkeypatch):
    """`fixture.test` resolves to loopback and loopback counts as public, until `dns["answer"]` is changed."""
    state = {"answer": "127.0.0.1"}
    real_is_public = net_guard._is_public
    monkeypatch.setattr(net_guard, "_resolve", lambda host: [state["answer"]] if host == FIXTURE_HOST else [])
    monkeypatch.setattr(net_guard, "_is_public", lambda a: a == "127.0.0.1" or real_is_public(a))
    return state


def _message(text: str) -> Message:
    return Message(role=Role.user, message_id="m1", parts=[Part(root=TextPart(text=text))])


def test_the_mcp_client_lists_and_calls_a_tool_on_a_real_server(servers, dns):
    port, recorded = servers

    async def go():
        manager = StreamableHttpTransportManager(endpoint=f"http://{FIXTURE_HOST}:{port}/mcp", headers={})
        async with manager:
            tools = await manager._session.list_tools()
            result = await manager._session.call_tool("echo", {"text": "hi"})
        return [t.name for t in tools.tools], result.content[0].text

    names, text = asyncio.run(go())
    assert "echo" in names and text == "echo: hi"
    assert recorded.hosts and all(h == f"{FIXTURE_HOST}:{port}" for h in recorded.hosts)  # the name survives pinning


def test_the_a2a_client_fetches_the_card_and_gets_an_answer_from_a_real_server(servers, dns):
    port, recorded = servers

    async def go():
        async with A2AClient(base_url=f"http://{FIXTURE_HOST}:{port}/a2a/") as client:
            return client.agent_card.name, await client.send(_message("ping"))

    name, result = asyncio.run(go())
    assert name == "Fixture agent"
    assert "echo: ping" in str(result)
    assert all(h == f"{FIXTURE_HOST}:{port}" for h in recorded.hosts)


def test_a_name_that_turns_private_after_connecting_is_refused_on_the_next_request(servers, dns):
    port, _ = servers

    async def go():
        async with create_guarded_mcp_http_client() as client:
            first = await client.get(f"http://{FIXTURE_HOST}:{port}/ping")
            dns["answer"] = "10.0.0.5"  # rebinding: the same name now answers with a private address
            with pytest.raises(UnsafeUrlError):
                await client.get(f"http://{FIXTURE_HOST}:{port}/ping")
        return first.text

    assert asyncio.run(go()) == "pong"


def test_a_redirect_from_a_real_server_to_the_metadata_address_is_not_followed(servers, dns):
    port, _ = servers

    async def go():
        async with create_guarded_mcp_http_client() as client:
            client.follow_redirects = True
            with pytest.raises(UnsafeUrlError):
                await client.get(f"http://{FIXTURE_HOST}:{port}/redirect")

    asyncio.run(go())
