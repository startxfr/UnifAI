"""R-540: a request nobody waits for any more is refused, not silently accepted, and clients are told it expired."""

import threading
import time

import pytest

from outbound.channels.local.input_channel import LocalInputCapableChannel
from outbound.hitl.channel_gate import ChannelApprovalGate
from mas.core.hitl.models import (
    ApprovalDecision, ApprovalRequest, ApprovalType, HITLConfig, RequestOrigin, ToolAccessMode,
)


def _request(request_id="r1"):
    return ApprovalRequest(
        request_id=request_id, type=ApprovalType.AGENT_ACTION,
        origin=RequestOrigin(node_uid="arkos", node_display_name="Arkos", session_id="s1"),
        tool_name="git.file.write", tool_args={}, tool_description="", tool_access_mode=ToolAccessMode.WRITE,
        reasoning="",
    )


def _events(queue):
    out = []
    while not queue.empty():
        kind, data = queue.get()
        if kind == "data":
            out.append(data)
    return out


def _channel():
    import queue
    q = queue.Queue()
    return LocalInputCapableChannel("s1", q), q


def test_a_request_is_pending_only_while_it_is_waited_for():
    channel, q = _channel()
    gate = ChannelApprovalGate(channel, HITLConfig(timeout_seconds=5))
    seen = {}

    def human():
        time.sleep(0.2)
        seen["pending"] = channel.is_pending("r1")
        channel.submit("r1", {"decision": "approve", "feedback": "ok"})

    t = threading.Thread(target=human)
    t.start()
    response = gate.request_approval(_request())
    t.join()
    assert seen["pending"] is True and response.decision == ApprovalDecision.APPROVE
    assert channel.is_pending("r1") is False
    assert [e["type"] for e in _events(q)] == ["approval_required"]


def test_a_timed_out_request_is_announced_as_expired_and_no_longer_pending():
    channel, q = _channel()
    gate = ChannelApprovalGate(channel, HITLConfig(timeout_seconds=0.2))
    assert gate.request_approval(_request()).decision == HITLConfig().timeout_decision
    assert channel.is_pending("r1") is False
    types = [e["type"] for e in _events(q)]
    assert types == ["approval_required", "approval_expired"]


def test_an_interrupted_wait_is_announced_as_expired_too():
    channel, q = _channel()

    class _Interrupted(BaseException):
        pass

    def boom(request_id, timeout):
        raise _Interrupted()

    channel.wait_for = boom
    gate = ChannelApprovalGate(channel, HITLConfig(timeout_seconds=5))
    with pytest.raises(_Interrupted):
        gate.request_approval(_request())
    assert channel.is_pending("r1") is False
    assert [e["type"] for e in _events(q)] == ["approval_required", "approval_expired"]


def test_a_channel_that_does_not_record_requests_never_refuses_an_answer():
    from mas.core.channels import InputCapableChannel
    channel = type("C", (InputCapableChannel,), {n: (lambda *a, **k: None) for n in InputCapableChannel.__abstractmethods__})()
    assert channel.is_pending("anything") is True


def test_the_redis_channel_records_the_request_with_a_ttl_and_forgets_it():
    from outbound.channels.redis.input_channel import RedisInputCapableChannel

    class _Redis:
        def __init__(self):
            self.keys = {}

        def set(self, key, value, ex=None):
            self.keys[key] = ex

        def exists(self, key):
            return key in self.keys

        def delete(self, key):
            self.keys.pop(key, None)

    channel = RedisInputCapableChannel.__new__(RedisInputCapableChannel)
    channel._session_id = "s1"
    channel._redis = _Redis()
    channel.mark_pending("r1", 300)
    assert channel.is_pending("r1") and list(channel._redis.keys.values()) == [330]
    channel.clear_pending("r1")
    assert not channel.is_pending("r1")


def test_every_channel_the_api_can_get_answers_is_pending_and_submit():
    """The API's session.approval calls these two on whatever get_input_channel returns. With Redis that is a proxy,
    not the running channel: 0.1.63 shipped without is_pending on it and answered 500 to every approval."""
    from outbound.channels.redis.factory import _RedisSubmitProxy
    from outbound.channels.redis.input_channel import RedisInputCapableChannel

    for cls in (LocalInputCapableChannel, _RedisSubmitProxy):
        assert callable(getattr(cls, "is_pending", None)) and callable(getattr(cls, "submit", None)), cls


def test_the_api_proxy_and_the_running_channel_agree_on_what_is_pending():
    from outbound.channels.redis.factory import _RedisSubmitProxy
    from outbound.channels.redis.input_channel import RedisInputCapableChannel

    class _Redis:
        def __init__(self):
            self.keys = {}

        def set(self, key, value, ex=None):
            self.keys[key] = ex

        def exists(self, key):
            return key in self.keys

        def delete(self, key):
            self.keys.pop(key, None)

    redis = _Redis()
    running = RedisInputCapableChannel.__new__(RedisInputCapableChannel)
    running._session_id, running._redis = "s1", redis
    api = _RedisSubmitProxy("s1", redis)
    assert api.is_pending("r1") is False  # nobody waits: the API must answer 409
    running.mark_pending("r1", 300)
    assert api.is_pending("r1") is True and _RedisSubmitProxy("s2", redis).is_pending("r1") is False
    running.clear_pending("r1")
    assert api.is_pending("r1") is False
