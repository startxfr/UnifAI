"""The guarded transports vet every request, pin the connection and re-vet redirect hops."""
import asyncio

import httpx
import pytest

from global_utils.utils.net_guard import UnsafeUrlError
from global_utils.utils.net_guard_httpx import GuardedAsyncTransport, GuardedTransport


def resolver_for(mapping):
    return lambda host: mapping[host]


class Recorder(httpx.AsyncBaseTransport):
    """Stands in for the network: records what would be sent and answers from a table."""

    def __init__(self, answers=None):
        self.seen = []
        self.answers = answers or {}

    async def handle_async_request(self, request):
        self.seen.append(request)
        status, headers = self.answers.get(request.headers["Host"] + request.url.path, (200, {}))
        return httpx.Response(status, headers=headers, request=request)


def run(coro):
    return asyncio.run(coro)


def client(recorder, mapping, **kw):
    transport = GuardedAsyncTransport(resolver=resolver_for(mapping), inner=recorder, **kw)
    return httpx.AsyncClient(transport=transport, follow_redirects=True)


def test_the_connection_goes_to_the_vetted_address_and_keeps_the_name():
    rec = Recorder()

    async def go():
        async with client(rec, {"mcp.example.com": ["93.184.216.34"]}) as c:
            return await c.get("https://mcp.example.com/mcp")

    assert run(go()).status_code == 200
    sent = rec.seen[0]
    assert sent.url.host == "93.184.216.34"
    assert sent.headers["Host"] == "mcp.example.com"
    assert sent.extensions["sni_hostname"] == "mcp.example.com"


def test_a_name_that_answers_privately_the_second_time_is_refused_at_connect():
    answers = iter([["93.184.216.34"], ["10.0.0.5"]])
    rec = Recorder()
    transport = GuardedAsyncTransport(resolver=lambda host: next(answers), inner=rec)

    async def go():
        async with httpx.AsyncClient(transport=transport) as c:
            await c.get("https://rebind.example.com/a")  # validated, pinned
            await c.get("https://rebind.example.com/b")  # now resolves privately

    with pytest.raises(UnsafeUrlError):
        run(go())
    assert [r.url.host for r in rec.seen] == ["93.184.216.34"]


@pytest.mark.parametrize("target", ["http://169.254.169.254/latest/meta-data/", "http://10.1.2.3/", "http://localhost:6379/"])
def test_a_redirect_to_a_non_public_target_is_refused(target):
    rec = Recorder({"mcp.example.com/mcp": (302, {"location": target})})

    async def go():
        async with client(rec, {"mcp.example.com": ["93.184.216.34"]}) as c:
            await c.get("https://mcp.example.com/mcp")

    with pytest.raises(UnsafeUrlError):
        run(go())
    assert len(rec.seen) == 1  # the second hop never reached the network


def test_a_redirect_between_public_hosts_is_followed_and_each_hop_is_pinned():
    rec = Recorder({"a.example.com/x": (302, {"location": "https://b.example.com/y"})})

    async def go():
        async with client(rec, {"a.example.com": ["93.184.216.34"], "b.example.com": ["93.184.216.35"]}) as c:
            return await c.get("https://a.example.com/x")

    assert run(go()).status_code == 200
    assert [r.url.host for r in rec.seen] == ["93.184.216.34", "93.184.216.35"]


def test_a_cluster_internal_name_connects_the_usual_way():
    rec = Recorder()

    async def go():
        async with client(rec, {}) as c:  # the resolver would KeyError if it were asked
            return await c.get("http://a2a-gateway.zuno-ai-run.svc.cluster.local:8080/agents/x/")

    assert run(go()).status_code == 200
    assert rec.seen[0].url.host == "a2a-gateway.zuno-ai-run.svc.cluster.local"


def test_the_sync_transport_pins_and_refuses_too():
    seen = []

    class Inner(httpx.BaseTransport):
        def handle_request(self, request):
            seen.append(request)
            return httpx.Response(200, request=request)

    t = GuardedTransport(resolver=resolver_for({"x.example.com": ["93.184.216.34"], "bad.example.com": ["10.0.0.9"]}), inner=Inner())
    with httpx.Client(transport=t) as c:
        assert c.get("https://x.example.com/").status_code == 200
        with pytest.raises(UnsafeUrlError):
            c.get("https://bad.example.com/")
    assert seen[0].url.host == "93.184.216.34" and seen[0].headers["Host"] == "x.example.com"
