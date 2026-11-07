"""R-543: the token ceiling of one turn."""
from types import SimpleNamespace

import pytest

from mas.elements.llms.common import token_budget as tb
from mas.elements.llms.common.exceptions import LLMRateLimitError
from mas.elements.llms.openai_compatible.openai_compatible import OpenAICompatibleLLM


@pytest.fixture(autouse=True)
def fresh_store():
    tb.configure(tb.InMemoryTokenBudgetStore())
    tb.bind_turn(None, None)
    yield
    tb.bind_turn(None, None)


def test_no_cap_or_no_turn_counts_and_refuses_nothing():
    tb.bind_turn("s1", "h1")
    tb.record(500, None)
    tb.check(None)
    tb.bind_turn(None, None)
    tb.record(500, 10)
    tb.check(10)


def test_the_ceiling_is_reached_per_turn_and_a_new_turn_starts_at_zero():
    tb.bind_turn("s1", "h1")
    tb.record(60, 100)
    tb.check(100)
    tb.record(50, 100)
    with pytest.raises(tb.TokenCeilingReached) as e:
        tb.check(100)
    assert str(e.value) == "Token ceiling reached for this turn (110/100 tokens)"
    assert isinstance(e.value, LLMRateLimitError)  # rides the non-fatal path of a rate limit: no 5xx
    assert e.value.to_dict()["type"] == tb.TOKEN_CEILING_TYPE
    tb.bind_turn("s1", "h2")  # the next user.session.submit
    tb.check(100)


def test_the_ceiling_event_is_announced_once_per_turn():
    tb.bind_turn("s1", "h1")
    assert tb.announce_once() is True
    assert tb.announce_once() is False
    tb.bind_turn("s1", "h2")
    assert tb.announce_once() is True


class _Completions:
    def __init__(self, total):
        self.total, self.calls = total, 0

    def create(self, **kw):
        self.calls += 1
        msg = SimpleNamespace(role="assistant", content="ok", tool_calls=None, function_call=None)
        return SimpleNamespace(id="r", model="m", choices=[SimpleNamespace(message=msg, finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=self.total))


def _llm(total):
    from mas.elements.llms.common.chat.message import ChatMessage, Role  # noqa: F401
    llm = OpenAICompatibleLLM(base_url="http://x/v1", model_name="m", tracing=_NoTracing())
    llm._client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions(total)))
    return llm


class _NoTracing:
    def trace_llm(self, **kw):
        class _Ctx:
            def __enter__(self_):
                return SimpleNamespace(update=lambda **k: None)

            def __exit__(self_, *a):
                return False
        return _Ctx()


def test_the_client_refuses_the_call_after_the_ceiling_and_counts_what_the_endpoint_reports():
    from mas.elements.llms.common.chat.message import ChatMessage, Role
    llm = _llm(70).with_token_cap(100)
    tb.bind_turn("s1", "h1")
    msgs = [ChatMessage(role=Role.USER, content="hi")]
    llm.chat(msgs)
    llm.chat(msgs)  # 70 used < 100: allowed, now 140
    with pytest.raises(tb.TokenCeilingReached):
        llm.chat(msgs)
    assert llm._client.chat.completions.calls == 2  # the third call never reached the endpoint


def test_a_client_without_cap_does_not_count():
    from mas.elements.llms.common.chat.message import ChatMessage, Role
    llm = _llm(70)
    tb.bind_turn("s1", "h1")
    for _ in range(3):
        llm.chat([ChatMessage(role=Role.USER, content="hi")])
    assert tb._store.used("s1:h1") == 0


class _CeilingIterator:
    """What the loop sees when the ceiling cuts the turn after the model said something."""

    def __init__(self, text):
        from mas.elements.llms.common.chat.message import ChatMessage, Role
        from mas.elements.nodes.common.agent.primitives import AgentStep, StepType
        planning = AgentStep(type=StepType.PLANNING, data=ChatMessage(role=Role.ASSISTANT, content=text), metadata={})
        error = AgentStep(type=StepType.ERROR, data=tb.TokenCeilingReached(120, 100),
                          metadata={"recoverable": False, "retry_after": None})
        self.history, self.observations, self._steps = [planning, error], [], [error]

    def __iter__(self):
        return iter(self._steps)


def _agent(events, text="Here is what I found so far."):
    from mas.elements.nodes.common.capabilities.agent_capable import AgentCapableMixin

    class _A(AgentCapableMixin[object]):
        def create_iterator(self, messages, strategy, *, config=None, on_action=None):
            return _CeilingIterator(text)

        def is_streaming(self):
            return True

        def _stream(self, event):
            events.append(event)

        def chat(self, messages, tools=None):
            raise AssertionError("no wrap-up call after a ceiling")

    return _A()


def _run(agent):
    from mas.elements.llms.common.chat.message import ChatMessage, Role
    from mas.elements.nodes.common.agent import AgentConfig

    class _S:
        strategy_name = "react"

    return agent.run_agent([ChatMessage(role=Role.USER, content="hi")], _S(), config=AgentConfig())


def test_the_turn_ends_cleanly_with_what_was_produced_then_the_notice_and_one_event():
    events = []
    tb.bind_turn("s1", "h1")
    result = _run(_agent(events))
    assert result["success"] is True and result["error"] is None
    assert result["output"] == "Here is what I found so far.\n\nToken ceiling reached for this turn (120/100 tokens)"
    assert [e["error_type"] for e in events if e.get("type") == "agent_error"] == [tb.TOKEN_CEILING_TYPE]
    again = []
    _run(_agent(again))  # a second node of the same turn reports it: the event is not repeated
    assert [e for e in again if e.get("type") == "agent_error"] == []


def test_a_turn_cut_before_the_model_said_anything_answers_with_the_notice_alone():
    result = _run(_agent([], text=""))
    assert result["output"] == "Token ceiling reached for this turn (120/100 tokens)"
