"""R-535 step 5: the approvals a remote agent asks for (input-required + zuno.approval) are relayed and answered."""

import asyncio
from types import SimpleNamespace

import pytest
from a2a.types import Message, Part, Role, TaskState, TextPart
from mas.elements.providers.a2a_client.converter import A2AConverter
from mas.elements.providers.a2a_client.provider import (
    A2AProvider, A2ATaskError, MAX_APPROVALS_PER_DELEGATION,
)
from mas.elements.providers.a2a_client.result import A2AResult

REQUEST = {"request_id": "r1", "operation": "git.file.write", "args": {"path": "a.md"}, "reasoning": "publish"}


def _state(name, approval=None):
    """An A2AResult-shaped stand-in for a polled task."""
    return SimpleNamespace(
        task_id="t1", context_id="c1", state=name, approval=approval,
        is_complete=name == "done", is_failure=name == "failed", requires_input=name == "input",
        requires_auth=name == "auth", error_message=None,
    )


class _Client:
    def __init__(self, polls, sends=()):
        self.polls, self.sends, self.answers, self.cancelled = list(polls), list(sends), [], []

    async def get_task(self, task_id):
        return self.polls.pop(0) if len(self.polls) > 1 else self.polls[0]

    async def send(self, message, blocking=None):
        self.answers.append(message)
        assert blocking is False
        return self.sends.pop(0) if self.sends else _state("working")

    async def cancel_task(self, task_id):
        self.cancelled.append(task_id)


def _run(client, on_approval, first=None):
    provider = A2AProvider.__new__(A2AProvider)
    provider._converter = A2AConverter()
    return asyncio.run(provider._await_result(client, first or _state("working"), 0.0, 20, False, None, on_approval))


def _answer(message):
    return message.parts[0].root.data["zuno.approval"]


def test_an_approval_request_is_relayed_and_the_answer_is_a_new_message_on_the_same_task():
    seen = []
    client = _Client([_state("input", REQUEST), _state("done")])
    result = _run(client, lambda a: seen.append(a) or ("approve", "ok"))
    assert result.state == "done" and seen == [REQUEST]
    (message,) = client.answers
    assert (message.task_id, message.context_id, message.role) == ("t1", "c1", Role.user)
    assert _answer(message) == {"request_id": "r1", "decision": "approve", "feedback": "ok"}


def test_a_stale_view_of_an_answered_request_is_not_asked_twice():
    asked = []
    client = _Client([_state("input", REQUEST), _state("input", REQUEST), _state("done")])
    _run(client, lambda a: asked.append(a) or ("approve", ""))
    assert len(asked) == 1 and len(client.answers) == 1


def test_without_a_handler_the_request_is_rejected():
    client = _Client([_state("input", REQUEST), _state("done")])
    _run(client, None)
    assert _answer(client.answers[0])["decision"] == "reject"


def test_a_failing_handler_rejects():
    def boom(_a):
        raise RuntimeError("redis down")

    client = _Client([_state("input", REQUEST), _state("done")])
    _run(client, boom)
    assert _answer(client.answers[0])["decision"] == "reject"


def test_only_approve_and_reject_are_ever_sent():
    client = _Client([_state("input", REQUEST), _state("done")])
    _run(client, lambda a: ("modify", "x"))
    assert _answer(client.answers[0])["decision"] == "reject"


def test_input_required_without_an_approval_is_returned_as_before():
    client = _Client([_state("input")])
    assert _run(client, lambda a: ("approve", "")).state == "input"
    assert client.answers == []


def test_authentication_required_is_a_clear_error_and_cancels_the_task():
    client = _Client([_state("auth")])
    with pytest.raises(A2ATaskError, match="requires authentication"):
        _run(client, None)
    assert client.cancelled == ["t1"]


def test_too_many_approvals_cancel_the_remote_task():
    polls = [_state("input", dict(REQUEST, request_id=f"r{i}")) for i in range(MAX_APPROVALS_PER_DELEGATION + 1)]
    client = _Client(polls)
    with pytest.raises(A2ATaskError, match="more than 5 approvals"):
        _run(client, lambda a: ("approve", ""))
    assert len(client.answers) == MAX_APPROVALS_PER_DELEGATION and client.cancelled == ["t1"]


def test_the_result_reads_the_request_from_the_status_message():
    from a2a.types import Task, TaskStatus

    message = Message(message_id="m", role=Role.agent, parts=[Part(root=TextPart(text="?"))],
                      metadata={"zuno.approval": REQUEST})
    task = Task(id="t1", context_id="c1", status=TaskStatus(state=TaskState.input_required, message=message))
    result = A2AResult.from_task(task)
    assert result.requires_input and result.approval == REQUEST
    bare = Task(id="t1", context_id="c1", status=TaskStatus(state=TaskState.input_required))
    assert A2AResult.from_task(bare).approval is None


def _node(mode, gate=None, active=True):
    from mas.elements.nodes.a2a_agent.a2a_agent_node import A2AAgentNode

    class _Node(A2AAgentNode):
        uid = "arkos"
        display_name = "Arkos"
        hitl_session_id = "s1"

    node = _Node.__new__(_Node)
    node._approval_gate = gate
    node._should_activate_hitl = lambda: active
    return node


class _Gate:
    def __init__(self, decision):
        self.decision, self.requests = decision, []

    def request_human_approval(self, request):
        from mas.core.hitl.models import ApprovalResponse
        self.requests.append(request)
        return ApprovalResponse(request_id=request.request_id, decision=self.decision, feedback="fb")

    def request_approval(self, request):  # the auto-approve rules must never be consulted
        raise AssertionError("auto-approve path used")


def test_the_node_relays_to_the_human_of_the_session_and_never_to_the_auto_rules():
    from mas.core.hitl.models import ApprovalDecision, ApprovalType, ToolAccessMode

    gate = _Gate(ApprovalDecision.APPROVE)
    assert _node("ask", gate)._on_remote_approval(REQUEST) == ("approve", "fb")
    (request,) = gate.requests
    assert (request.request_id, request.tool_name, request.tool_args) == ("r1", "git.file.write", {"path": "a.md"})
    assert request.type == ApprovalType.AGENT_ACTION and request.tool_access_mode == ToolAccessMode.WRITE
    assert request.origin.node_uid == "arkos" and request.origin.session_id == "s1"


def test_the_node_rejects_when_no_human_can_be_asked_or_the_decision_is_not_supported():
    from mas.core.hitl.models import ApprovalDecision

    assert _node("skip", None, active=False)._on_remote_approval(REQUEST)[0] == "reject"
    assert _node("ask", _Gate(ApprovalDecision.REJECT))._on_remote_approval(REQUEST) == ("reject", "fb")
    decision, _ = _node("ask", _Gate(ApprovalDecision.MODIFY))._on_remote_approval(REQUEST)
    assert decision == "reject"


def test_the_auto_resolving_gate_does_not_apply_its_rules_to_a_relayed_request():
    from adapters.outbound.hitl.auto_resolving_gate import AutoResolvingApprovalGate
    from mas.core.hitl.models import ApprovalDecision, HITLConfig

    inner = _Gate(ApprovalDecision.APPROVE)
    gate = AutoResolvingApprovalGate(inner=inner, overrides_store=None, session_id="s", config=HITLConfig())
    assert gate.request_human_approval(SimpleNamespace(request_id="r1")).feedback == "fb"
    assert len(inner.requests) == 1
