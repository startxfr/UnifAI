"""A work item is delegated a bounded number of times (0.1.52: the model re-asked Tekos 11 times per user turn)."""
from types import SimpleNamespace

import pytest

from mas.elements.nodes.common.workload import WorkItemStatus
from mas.elements.tools.builtin.delegation.delegate_task import (
    DEFAULT_MAX_DELEGATIONS,
    MAX_DELEGATIONS_ENV,
    DelegateTaskTool,
    delegation_cap_reached,
    max_delegations_per_item,
)


def _exchange(answer):
    return SimpleNamespace(response_content=answer, processed=False)


def _item(*answers):
    return SimpleNamespace(result=SimpleNamespace(delegations=[_exchange(a) for a in answers], success=None),
                           status=WorkItemStatus.IN_PROGRESS, error=None)


class _Service:
    def __init__(self, item):
        self.item = item

    def atomic_update_work_item(self, thread_id, owner_uid, item_id, update):
        update(self.item, None)
        return True


def test_the_cap_defaults_to_three_and_zero_means_unlimited(monkeypatch):
    monkeypatch.delenv(MAX_DELEGATIONS_ENV, raising=False)
    assert max_delegations_per_item() == DEFAULT_MAX_DELEGATIONS == 3
    monkeypatch.setenv(MAX_DELEGATIONS_ENV, "5")
    assert max_delegations_per_item() == 5
    monkeypatch.setenv(MAX_DELEGATIONS_ENV, "not a number")
    assert max_delegations_per_item() == 3
    monkeypatch.setenv(MAX_DELEGATIONS_ENV, "0")
    assert max_delegations_per_item() == 0 and not delegation_cap_reached(_item("a", "b", "c", "d"), 0)


@pytest.mark.parametrize("answers,reached", [((), False), (("a",), False), (("a", "b"), False), (("a", "b", "c"), True),
                                             (("a", None, None), True)])
def test_the_cap_counts_every_delegation_of_the_item(answers, reached):
    assert delegation_cap_reached(_item(*answers), 3) is reached
    assert delegation_cap_reached(None, 3) is False


def test_a_capped_item_with_answers_is_closed_done_and_nothing_is_sent():
    item = _item("first", "second", "third")
    out = DelegateTaskTool._close_capped_item(_Service(item), "t", "orch", "ask_tekos", item, 3)
    assert out["success"] is False and "marked done" in out["error"] and "Do NOT delegate" in out["error"]
    assert item.status == WorkItemStatus.DONE and item.result.success is True
    assert all(e.processed for e in item.result.delegations)


def test_a_capped_item_without_any_answer_is_failed():
    item = _item(None, None, None)
    out = DelegateTaskTool._close_capped_item(_Service(item), "t", "orch", "ask_tekos", item, 3)
    assert "marked failed" in out["error"]
    assert item.status == WorkItemStatus.FAILED and "3 delegations" in item.error
