"""A control token leaked into a tool call name (Harmony, vLLM) does not make the call unknown."""

import logging

from mas.elements.llms.common.chat.message import ChatMessage, Role, ToolCall
from mas.elements.llms.common.tool_name_restorer import restore_tool_names

REV = {"iem_delegate_task": "iem.delegate_task", "time_now": "time.now"}


def _msg(*names):
    return ChatMessage(role=Role.ASSISTANT, content="", tool_calls=[
        ToolCall(name=n, args={}, tool_call_id=f"c{i}") for i, n in enumerate(names)])


def _names(msg):
    return [tc.name for tc in msg.tool_calls]


def test_a_known_sanitized_name_is_restored():
    assert _names(restore_tool_names(REV, _msg("iem_delegate_task"))) == ["iem.delegate_task"]


def test_a_control_token_suffix_is_cut_and_the_name_restored(caplog):
    with caplog.at_level(logging.WARNING):
        out = restore_tool_names(REV, _msg("iem_delegate_task<|channel|>commentary", "time_now"))
    assert _names(out) == ["iem.delegate_task", "time.now"]
    assert any(r.getMessage() == "llm.tool_name_control_token" for r in caplog.records)


def test_a_domain_name_with_a_suffix_is_cut_too():
    assert _names(restore_tool_names(REV, _msg("time.now<|channel|>x"))) == ["time.now"]


def test_an_unknown_name_with_a_token_is_left_alone():
    assert _names(restore_tool_names(REV, _msg("nothing<|channel|>commentary"))) == ["nothing<|channel|>commentary"]


def test_a_message_without_tool_calls_is_unchanged():
    msg = ChatMessage(role=Role.ASSISTANT, content="hi")
    assert restore_tool_names(REV, msg) is msg
