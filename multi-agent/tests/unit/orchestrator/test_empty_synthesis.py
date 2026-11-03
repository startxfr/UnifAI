"""A delegating turn whose final model message is empty answers with the delegated agents' answers."""

from types import SimpleNamespace

from mas.elements.nodes.orchestrator.empty_synthesis import delegated_answers, is_empty_answer
from mas.elements.nodes.orchestrator.orchestrator_node import OrchestratorNode


def _item(*responses):
    return SimpleNamespace(result=SimpleNamespace(delegations=[SimpleNamespace(response_content=r) for r in responses]))


def test_what_counts_as_empty():
    for value in (None, "", "   ", "None", "null"):
        assert is_empty_answer(value)
    assert not is_empty_answer("Tekos says X")


def test_delegated_answers_are_joined_without_duplicates():
    assert delegated_answers([_item("A", None, "  "), _item("A", "B")]) == "A\n\nB"
    assert delegated_answers([_item(None), SimpleNamespace(result=None)]) is None


class _Workspaces:
    def __init__(self, plan):
        self.plan = plan

    def load_work_plan(self, thread, owner):
        return self.plan


def _node(plan):
    return SimpleNamespace(uid="orch", workspaces=_Workspaces(plan))


def test_the_fallback_uses_the_delegated_answers():
    node = _node(SimpleNamespace(items=[_item("Tekos: use 2 GPUs")]))
    assert OrchestratorNode._answer_from_delegations(node, "t1", "") == ("Tekos: use 2 GPUs", True)


def test_no_delegated_answer_keeps_the_output():
    assert OrchestratorNode._answer_from_delegations(_node(SimpleNamespace(items=[_item(None)])), "t1", "") == ("", False)
    assert OrchestratorNode._answer_from_delegations(_node(None), "t1", "") == ("", False)
