"""R-569: the span `execute_tool iem.delegate_task` carries `mas.delegation.after_rate_limit`, true when the previous answer of
the same work item was cut by a rate limit (429), so that the traces tell a re-delegation caused by the provider from one
caused by the model. Nothing changes for the model: the tool result is the same.

Seam: BaseTool.span_attributes(args) -> {"delegation.after_rate_limit": bool}, called by the tracing pre-hook of
AgentCapableMixin._ensure_executor right after the span is opened. The previous answer carries the error the way the
orchestrator stores it: response_data = AgentResult.model_dump(), whose execution_metadata has error_type = "rate_limited"
(custom_agent._rate_limit_metadata) or error.type = "rate_limited" (ERROR_METADATA_KEY)."""
import asyncio
from types import SimpleNamespace

import pytest

from mas.elements.nodes.common.workload import DelegationExchange, WorkItemKind, WorkItemStatus
from mas.elements.nodes.common.workload.models import AgentResult
from mas.elements.nodes.common.capabilities.agent_capable import AgentCapableMixin
from mas.elements.tools.builtin.delegation.delegate_task import (
    MAX_DELEGATIONS_ENV,
    DelegateTaskTool,
    previous_response_rate_limited,
)

ITEM = "launch_audit"


def _answer(**metadata):
    """The AgentResult dump of an answer whose agent hit the given error."""
    result = AgentResult(content="Rate limit reached, retry later.", agent_id="a2a-tekos", agent_name="Tekos",
                         success=False, execution_metadata=metadata)
    return result.model_dump()


def _exchange(sequence, response_data=None, answered=True):
    return DelegationExchange(sequence=sequence, task_id=f"t{sequence}", query="q", delegated_to="a2a-tekos",
                              response_content="answer" if answered else None, response_data=response_data)


class _Workspace:
    def __init__(self, exchanges):
        self.item = SimpleNamespace(kind=WorkItemKind.REMOTE, child_thread_id="child", status=WorkItemStatus.IN_PROGRESS,
                                    result=SimpleNamespace(delegations=exchanges), description="d", assigned_uid=None,
                                    error=None)
        self.plan = SimpleNamespace(items={ITEM: self.item})

    def load_work_plan(self, thread_id, owner_uid):
        return self.plan

    def atomic_update_work_item(self, thread_id, owner_uid, item_id, update):
        update(self.item, self.plan)
        return True


class _Threads:
    def get_thread(self, thread_id):
        return SimpleNamespace(thread_id=thread_id)

    def save_thread(self, thread):
        pass

    def detect_delegation_cycle(self, thread_id, dst_uid):
        return False


def _tool(exchanges):
    workspace = _Workspace(exchanges)
    thread = SimpleNamespace(thread_id="parent", create_child=lambda **k: SimpleNamespace(thread_id="child"))
    tool = DelegateTaskTool(send_task=lambda dst, task: "packet-1", get_owner_uid=lambda: "orch",
                            get_current_thread=lambda: thread, get_thread_service=lambda: _Threads(),
                            get_workspace_service=lambda: workspace)
    return tool, workspace


ARGS = {"dst_uid": "a2a-tekos", "content": "again please", "work_item_id": ITEM}
KEY = "delegation.after_rate_limit"


def _delegate(exchanges):
    tool, _ = _tool(exchanges)
    return tool.run(**ARGS)


def _flags(exchanges):
    tool, _ = _tool(exchanges)
    return tool.span_attributes(dict(ARGS))


@pytest.fixture(autouse=True)
def _cap(monkeypatch):
    monkeypatch.setenv(MAX_DELEGATIONS_ENV, "5")  # the cap is not what most of these tests are about


# -- the pure decision
def _item(*exchanges):
    return SimpleNamespace(result=SimpleNamespace(delegations=list(exchanges)))


@pytest.mark.parametrize("item,expected", [
    (None, False),
    (SimpleNamespace(result=None), False),
    (_item(), False),
    (_item(_exchange(0, _answer(error_type="rate_limited"))), True),
    (_item(_exchange(0, _answer(error={"type": "rate_limited", "message": "429"}))), True),   # agent_capable run_agent form
    (_item(_exchange(0, _answer(error_type="token_ceiling"))), False),                        # another error: no
    (_item(_exchange(0, _answer(error={"type": "token_ceiling"}))), False),
    (_item(_exchange(0, _answer())), False),
    (_item(_exchange(0, None)), False),                                                       # no structured data
    (_item(_exchange(0, _answer(error_type="rate_limited")), _exchange(1, None, answered=False)), False),  # still waiting
    (_item(_exchange(0, _answer(error_type="rate_limited")), _exchange(1, _answer())), False),  # the LAST answer decides
    (_item(_exchange(0, _answer()), _exchange(1, _answer(error_type="rate_limited"))), True),
])
def test_previous_response_rate_limited(item, expected):
    assert previous_response_rate_limited(item) is expected


# -- the tool
def test_span_attributes_after_a_429_and_without():
    assert _flags([_exchange(0, _answer(error_type="rate_limited", retry_after=30))]) == {KEY: True}
    assert _flags([_exchange(0, _answer())]) == {KEY: False}
    assert _flags([]) == {KEY: False}  # first delegation: false, not absent


def test_span_attributes_are_empty_when_the_plan_the_item_or_the_thread_is_missing():
    tool, workspace = _tool([_exchange(0, _answer(error_type="rate_limited"))])
    assert tool.span_attributes({**ARGS, "work_item_id": "unknown"}) == {}
    workspace.plan = None
    assert tool.span_attributes(dict(ARGS)) == {}
    tool._get_current_thread = lambda: None
    assert tool.span_attributes(dict(ARGS)) == {}


def test_span_attributes_carry_no_content():
    attrs = _flags([_exchange(0, _answer(error_type="rate_limited"))])
    assert set(attrs) == {KEY} and all(isinstance(v, bool) for v in attrs.values())


def test_the_tool_result_the_model_sees_is_unchanged():
    out = _delegate([_exchange(0, _answer(error_type="rate_limited"))])
    assert out["success"] is True
    assert "after_rate_limit" not in out and "delegation.after_rate_limit" not in out


def test_a_refusal_by_the_cap_is_unchanged(monkeypatch):
    monkeypatch.setenv(MAX_DELEGATIONS_ENV, "2")
    out = _delegate([_exchange(0, _answer(error_type="rate_limited")), _exchange(1, _answer(error_type="rate_limited"))])
    assert out["success"] is False
    assert out["error"].startswith("Work item launch_audit was already delegated 2 times and is marked done with the answers received.")
    assert "Do NOT delegate it again" in out["error"]
    assert "after_rate_limit" not in out


# -- the pre-hook of the tool tracing (agent_capable) and the span
class _Handle:
    def __init__(self):
        self.updates = []

    def update(self, **kw):
        self.updates.append(kw)


class _Tracing:
    enabled = True

    def __init__(self):
        self.handle, self.opened = _Handle(), []

    def trace_tool(self, tool_name, tool_input=None):
        tracing = self

        class _Cm:
            def __enter__(self):
                tracing.opened.append((tool_name, tool_input))
                return tracing.handle

            def __exit__(self, *a):
                return False

        return _Cm()


def _manager(tracing):
    me = SimpleNamespace(_default_executor_config=None, _custom_pre_hooks=[], _custom_post_hooks=[], _tracing=tracing,
                         _tool_executor_manager=None)
    return AgentCapableMixin._ensure_executor(me, [])


def _pre_hook(tracing):
    return _manager(tracing)._pre_execution_hooks[-1]  # the tracing hook is registered last


def _call(hook, tool, args):
    asyncio.run(hook(tool, args, {"tool_call_id": "c1"}))


def test_the_pre_hook_puts_the_tool_attributes_on_the_span_it_opened():
    tracing = _Tracing()
    tool, _ = _tool([_exchange(0, _answer(error_type="rate_limited"))])
    _call(_pre_hook(tracing), tool, dict(ARGS))
    assert tracing.opened and tracing.opened[0][0] == "iem.delegate_task"
    assert tracing.handle.updates == [{"metadata": {KEY: True}}]


def test_a_tool_without_span_attributes_triggers_no_update():
    tracing = _Tracing()
    tool = SimpleNamespace(name="search", span_attributes=lambda args: {})
    _call(_pre_hook(tracing), tool, {"q": "x"})
    assert tracing.opened and tracing.handle.updates == []


def test_a_failing_span_attributes_breaks_nothing_and_warns_with_the_class_only(caplog):
    import logging
    tracing = _Tracing()

    def boom(args):
        raise RuntimeError("workspace down: mongodb://user:s3cr3t@db")

    tool = SimpleNamespace(name="iem.delegate_task", span_attributes=boom)
    with caplog.at_level(logging.DEBUG):
        _call(_pre_hook(tracing), tool, dict(ARGS))  # no exception: the tool goes on to run
    assert tracing.opened and tracing.handle.updates == []
    loud = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(loud) == 1  # exactly one warning...
    message = loud[0].getMessage()
    assert "RuntimeError" in message  # ...that names the class,
    assert "s3cr3t" not in message and "workspace down" not in message and "mongodb" not in message  # never the message
    assert loud[0].exc_info is None  # nor a traceback (the detail is DEBUG only)


def test_end_to_end_the_span_has_the_attribute_after_a_429_and_false_otherwise():
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from outbound.otel import OtelTracingService

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    manager = _manager(OtelTracingService(tracer_provider=provider))
    pre, post = manager._pre_execution_hooks[-1], manager._post_execution_hooks[-1]
    for call_id, answers in (("c1", [_exchange(0, _answer(error_type="rate_limited"))]), ("c2", [_exchange(0, _answer())])):
        tool, _ = _tool(answers)
        asyncio.run(pre(tool, dict(ARGS), {"tool_call_id": call_id}))
        response = SimpleNamespace(tool_call_id=call_id, success=True, tool_name="iem.delegate_task", error=None,
                                   result={"success": True, "task_id": "t"})
        asyncio.run(post(response, {"tool_call_id": call_id}))
    by_name = [s for s in exporter.get_finished_spans() if s.name == "execute_tool iem.delegate_task"]
    assert [s.attributes.get("mas.delegation.after_rate_limit") for s in by_name] == [True, False]
    for span in by_name:  # merged with the identifiers of R-560, not replacing them
        assert span.attributes["mas.delegation.work_item_id"] == ITEM
        assert span.attributes["mas.delegation.target"] == "a2a-tekos"

    # another tool: no delegation attribute at all; a work item that is not in the plan: no after_rate_limit attribute
    other = SimpleNamespace(name="search", span_attributes=lambda args: {})
    asyncio.run(pre(other, {"q": "x"}, {"tool_call_id": "c3"}))
    asyncio.run(post(SimpleNamespace(tool_call_id="c3", success=True, tool_name="search", error=None, result="ok"),
                     {"tool_call_id": "c3"}))
    tool, _ = _tool([_exchange(0, _answer(error_type="rate_limited"))])
    asyncio.run(pre(tool, {**ARGS, "work_item_id": "unknown"}, {"tool_call_id": "c4"}))
    asyncio.run(post(SimpleNamespace(tool_call_id="c4", success=True, tool_name="iem.delegate_task", error=None,
                                     result={"success": True}), {"tool_call_id": "c4"}))
    spans = {s.name: s for s in exporter.get_finished_spans() if s.attributes.get("gen_ai.tool.name") in ("search",)}
    assert not any(k.startswith("mas.delegation") for k in spans["execute_tool search"].attributes)
    unknown = [s for s in exporter.get_finished_spans() if s.attributes.get("mas.delegation.work_item_id") == "unknown"]
    assert len(unknown) == 1 and "mas.delegation.after_rate_limit" not in unknown[0].attributes
