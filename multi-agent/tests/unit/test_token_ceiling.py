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
