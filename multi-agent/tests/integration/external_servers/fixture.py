"""A real MCP server and a real A2A server on a local port, standing in for a third party's servers.

No mock transport sits between the client and the server: requests cross a socket. The servers record the
``Host`` header of every request, so a test can prove the guarded clients connect to the vetted address while
keeping the original name. :func:`public_looking` makes a made-up host name resolve to the loopback address
and count as public for the guard, which is the only way to exercise the pinning path without a public server.
"""
from __future__ import annotations

import contextlib
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Iterator

import uvicorn
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AFastAPIApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from a2a.utils import new_agent_text_message
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse
from starlette.routing import Mount, Route

FIXTURE_HOST = "fixture.test"


@dataclass
class Recorded:
    hosts: list[str] = field(default_factory=list)


class _EchoExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        text = context.get_user_input()
        await event_queue.enqueue_event(new_agent_text_message(f"echo: {text}"))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:  # pragma: no cover
        raise NotImplementedError


def _agent_card(base_url: str) -> AgentCard:
    return AgentCard(
        name="Fixture agent", description="Echoes what it is sent", url=base_url + "/a2a/", version="1.0.0",
        preferred_transport="JSONRPC",
        capabilities=AgentCapabilities(streaming=False, push_notifications=False, state_transition_history=False),
        default_input_modes=["text/plain"], default_output_modes=["text/plain"],
        skills=[AgentSkill(id="echo", name="echo", description="Echo", tags=["test"])],
    )


def build_app(base_url: str, recorded: Recorded) -> Starlette:
    mcp = FastMCP(
        "fixture-mcp", stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool()
    def echo(text: str) -> str:
        """Echo the text."""
        return f"echo: {text}"

    handler = DefaultRequestHandler(agent_executor=_EchoExecutor(), task_store=InMemoryTaskStore())
    a2a_app = A2AFastAPIApplication(agent_card=_agent_card(base_url), http_handler=handler).build()

    async def redirect_to_metadata(_: Request):
        return RedirectResponse("http://169.254.169.254/latest/meta-data/", status_code=302)

    async def ping(_: Request):
        return PlainTextResponse("pong")

    mcp_app = mcp.streamable_http_app()

    class Record:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                recorded.hosts.append(dict(scope["headers"]).get(b"host", b"").decode())
            await self.app(scope, receive, send)

    inner = Starlette(
        routes=[
            Route("/redirect", redirect_to_metadata),
            Route("/ping", ping),
            Mount("/a2a", app=a2a_app),
            Mount("/", app=mcp_app),
        ],
        lifespan=mcp_app.router.lifespan_context,
    )
    return Record(inner)  # type: ignore[return-value]


@contextlib.contextmanager
def running_servers() -> Iterator[tuple[int, Recorded]]:
    """Start the fixture on a free local port; yield ``(port, recorded)``."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    recorded = Recorded()
    config = uvicorn.Config(build_app(f"http://{FIXTURE_HOST}:{port}", recorded), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("fixture server did not start")
        time.sleep(0.05)
    try:
        yield port, recorded
    finally:
        server.should_exit = True
        thread.join(timeout=10)
