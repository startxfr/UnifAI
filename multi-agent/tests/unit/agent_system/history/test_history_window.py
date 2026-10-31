"""History window: recent turns kept by count and by token budget, oldest dropped whole."""
import pytest

from mas.elements.llms.common.chat.message import ChatMessage, Role
from mas.elements.nodes.common.workload.history_window import window_history

pytestmark = pytest.mark.unit


def convo(n, size=40):
    out = []
    for i in range(n):
        out.append(ChatMessage(role=Role.USER, content=f"q{i} " + "x" * size))
        out.append(ChatMessage(role=Role.ASSISTANT, content=f"a{i} " + "y" * size))
    return out


def test_no_limit_keeps_everything():
    assert len(window_history(convo(10))) == 20


def test_disabled_keeps_nothing():
    assert window_history(convo(3), enabled=False) == []


def test_max_turns_keeps_the_most_recent_whole_turns():
    kept = window_history(convo(10), max_turns=6)
    assert len(kept) == 12
    assert kept[0].content.startswith("q4") and kept[-1].content.startswith("a9")


def test_token_budget_drops_the_oldest_turns():
    # a message is 43 chars = 11 tokens, so a turn is 22 tokens
    kept = window_history(convo(10), token_budget=50)
    assert len(kept) == 4 and kept[0].content.startswith("q8")


def test_the_newest_turn_is_kept_even_over_budget():
    kept = window_history(convo(3, size=4000), token_budget=10)
    assert len(kept) == 2 and kept[0].content.startswith("q2")


def test_both_limits_apply():
    assert len(window_history(convo(10), max_turns=6, token_budget=50)) == 4


def test_messages_before_the_first_user_message_form_a_turn():
    msgs = [ChatMessage(role=Role.ASSISTANT, content="hello")] + convo(1)
    assert len(window_history(msgs, max_turns=1)) == 2


def test_the_orchestrator_applies_the_window_to_the_history_it_sends():
    from types import SimpleNamespace

    from mas.elements.nodes.orchestrator.orchestrator_node import OrchestratorNode

    class Node(OrchestratorNode):
        workspaces = SimpleNamespace(get_conversation_history=lambda _thread: convo(5))

    node = object.__new__(Node)
    node.history_enabled, node.history_max_turns, node.history_token_budget = True, 2, None
    out = node._build_context_messages("t", "q5 now")
    assert [m.content.split()[0] for m in out] == ["q3", "a3", "q4", "a4", "q5"], "two recent turns, then the prompt"
    node.history_enabled = False
    assert [m.content for m in node._build_context_messages("t", "q5 now")] == ["q5 now"]
