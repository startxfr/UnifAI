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
