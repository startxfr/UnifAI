"""An agent run does not execute the same tool call (same tool, same arguments) more than MAX_IDENTICAL_TOOL_CALLS times."""
from types import SimpleNamespace

import pytest

from mas.elements.nodes.common.agent.constants import ToolExecutionDefaults
from mas.elements.nodes.common.agent.execution.executor import AgentActionExecutor
from mas.elements.nodes.common.agent.primitives import AgentAction


class FakeManager:
    """Executes every request and records it."""

    def __init__(self):
        self.calls = []

    def has_tool(self, name):
        return name in ("web_search", "docs")

    async def execute_requests_async(self, requests):
        self.calls.extend((r.tool_name, r.args) for r in requests)
        responses = {r.tool_call_id: SimpleNamespace(result=f"result of {r.args}", success=True, error=None,
                                                     tool_call_id=r.tool_call_id) for r in requests}
        return SimpleNamespace(get_response=responses.get)


def search(query):
    return AgentAction(tool="web_search", tool_input={"query": query, "limit": 5})


def test_identical_calls_stop_being_executed_after_the_limit():
    manager = FakeManager()
    executor = AgentActionExecutor(tool_executor_manager=manager, validate_args=False)
    limit = ToolExecutionDefaults.MAX_IDENTICAL_TOOL_CALLS

    for _ in range(limit):
        (obs,) = executor.execute_batch([search("namespace")])
        assert obs.success and not obs.metadata.get("repeated_call")
    (obs,) = executor.execute_batch([search("namespace")])

    assert len(manager.calls) == limit
    assert obs.success and obs.metadata["repeated_call"]
    assert "answer from what you already have" in obs.content


def test_argument_order_does_not_matter_and_other_calls_still_run():
    manager = FakeManager()
    executor = AgentActionExecutor(tool_executor_manager=manager, validate_args=False, max_identical_calls=1)

    executor.execute_batch([search("namespace")])
    same = AgentAction(tool="web_search", tool_input={"limit": 5, "query": "namespace"})
    other_query = search("pod")
    other_tool = AgentAction(tool="docs", tool_input={"query": "namespace", "limit": 5})
    observations = {o.action_id: o for o in executor.execute_batch([same, other_query, other_tool])}

    assert observations[same.id].metadata.get("repeated_call")
    assert not observations[other_query.id].metadata.get("repeated_call")
    assert not observations[other_tool.id].metadata.get("repeated_call")
    assert [c[0] for c in manager.calls] == ["web_search", "web_search", "docs"]


def test_a_new_executor_starts_a_new_count():
    manager = FakeManager()
    first = AgentActionExecutor(tool_executor_manager=manager, validate_args=False, max_identical_calls=1)
    first.execute_batch([search("namespace")])
    second = AgentActionExecutor(tool_executor_manager=manager, validate_args=False, max_identical_calls=1)
    (obs,) = second.execute_batch([search("namespace")])
    assert not obs.metadata.get("repeated_call")
    assert len(manager.calls) == 2


@pytest.mark.parametrize("args", [{"blob": object()}, {"nested": {"b": [1, 2], "a": None}}])
def test_unusual_arguments_are_still_keyed(args):
    manager = FakeManager()
    executor = AgentActionExecutor(tool_executor_manager=manager, validate_args=False, max_identical_calls=1)
    (obs,) = executor.execute_batch([AgentAction(tool="docs", tool_input=args)])
    assert obs.success
