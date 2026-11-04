"""ADR-0406 clause 4: the A2A client cancels the remote task when it stops waiting for it."""

import asyncio
from types import SimpleNamespace

import pytest
from mas.elements.providers.a2a_client.provider import (
    A2AProvider, A2ATaskError, A2ATimeoutError,
)


class _Client:
    def __init__(self, states, cancel_error=None):
        self.states = list(states)
        self.cancelled = []
        self.cancel_error = cancel_error

    async def get_task(self, task_id):
        state = self.states.pop(0) if self.states else "working"
        if isinstance(state, BaseException):
            raise state
        return SimpleNamespace(is_complete=state == "done", is_failure=state == "failed", requires_input=False,
                               requires_auth=False, state=state, error_message="boom")

    async def cancel_task(self, task_id):
        if self.cancel_error:
            raise self.cancel_error
        self.cancelled.append(task_id)


def _poll(client, attempts=3, raise_on_error=False):
    provider = A2AProvider.__new__(A2AProvider)
    return provider._poll(client, "t1", 0.0, attempts, raise_on_error)


def test_a_timeout_cancels_the_remote_task():
    client = _Client(["working"] * 5)
    with pytest.raises(A2ATimeoutError):
        asyncio.run(_poll(client))
    assert client.cancelled == ["t1"]


def test_an_answer_cancels_nothing():
    client = _Client(["working", "done"])
    assert asyncio.run(_poll(client)).state == "done"
    assert client.cancelled == []


def test_a_task_that_failed_on_its_own_is_not_cancelled():
    client = _Client(["failed"])
    with pytest.raises(A2ATaskError):
        asyncio.run(_poll(client, raise_on_error=True))
    assert client.cancelled == []


def test_our_own_cancellation_cancels_the_remote_task():
    client = _Client([asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_poll(client))
    assert client.cancelled == ["t1"]


def test_a_failing_cancel_does_not_hide_the_timeout():
    client = _Client(["working"] * 5, cancel_error=RuntimeError("gateway down"))
    with pytest.raises(A2ATimeoutError):
        asyncio.run(_poll(client))


def test_a_non_blocking_send_asks_the_server_for_the_task_at_once():
    from unittest.mock import MagicMock
    from a2a.types import Message, Part, Role, TextPart
    from mas.elements.providers.a2a_client.client import A2AClient

    sent = []

    class _Sdk:
        async def send_message(self, request):
            sent.append(request)
            return MagicMock()

    for blocking, want in ((None, None), (False, False), (True, True)):
        client = A2AClient.__new__(A2AClient)
        client._sdk = _Sdk()
        client._handle_send_response = lambda _r: "result"
        message = Message(message_id="m1", role=Role.user, parts=[Part(root=TextPart(text="hi"))])
        asyncio.run(client.send(message, blocking=blocking))
        configuration = sent[-1].params.configuration
        assert (configuration.blocking if configuration else None) is want


def test_the_node_timeout_is_optional_and_positive():
    import pytest as _pytest
    from mas.elements.nodes.a2a_agent.config import A2AAgentNodeConfig
    field = A2AAgentNodeConfig.model_fields["timeout_seconds"]
    assert field.default is None
    with _pytest.raises(Exception):
        A2AAgentNodeConfig(base_url="http://gw:8080/agents/tekos", timeout_seconds=0)


def test_the_timeout_says_what_became_of_the_remote_task():
    client = _Client(["working"] * 5)
    with pytest.raises(A2ATimeoutError) as info:
        asyncio.run(_poll(client))
    assert (info.value.task_id, info.value.cancelled, info.value.timeout_seconds) == ("t1", True, 0.0)

    failing = _Client(["working"] * 5, cancel_error=RuntimeError("gateway down"))
    with pytest.raises(A2ATimeoutError) as info:
        asyncio.run(_poll(failing))
    assert info.value.cancelled is False


def _node(tracing=None):
    from mas.elements.nodes.a2a_agent.a2a_agent_node import A2AAgentNode
    class _Node(A2AAgentNode):
        uid = "tekos"
        display_name = "Tekos"

    node = _Node.__new__(_Node)
    node._tracing = tracing
    return node


def _timeout(cancelled):
    e = A2ATimeoutError("Polling timeout after 5.0s")
    e.task_id, e.timeout_seconds, e.cancelled = "t1", 5.0, cancelled
    return e


def test_the_orchestrator_is_told_plainly_that_the_delegation_timed_out_and_was_cancelled():
    text = _node()._error_text(_timeout(True))
    assert "timed out after 5s" in text and "remote task was cancelled" in text
    assert "may still be running" in _node()._error_text(_timeout(False))
    assert _node()._error_text(RuntimeError("x")) == "Error delegating to remote agent: x"


def test_the_timeout_is_recorded_on_the_delegation_span():
    from contextlib import contextmanager
    from mas.core.tracing.models import ObservationHandle

    updates, spans = [], []

    class _Tracing:
        @contextmanager
        def trace_node(self, node_uid, node_type, display_name=""):
            spans.append((node_uid, node_type))
            yield ObservationHandle(_update_fn=lambda **kw: updates.append(kw))

    node = _node(_Tracing())

    def boom(ctx, task):
        raise _timeout(True)

    node._delegate_to_remote_agent = boom
    with pytest.raises(A2ATimeoutError):
        node._delegate_traced([], None)
    assert spans == [("tekos/delegation", "a2a_delegation")]
    assert updates[0]["level"] == "ERROR"
    assert updates[0]["metadata"] == {"a2a_timeout": True, "a2a_timeout_seconds": 5.0,
                                      "a2a_task_id": "t1", "a2a_cancel": "cancelled"}
