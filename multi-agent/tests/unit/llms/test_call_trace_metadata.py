"""The trace of a model call carries the generation ceiling and the X-Zuno-Max-Tokens header it sends (R-519)."""

from contextlib import contextmanager
from unittest.mock import MagicMock

import httpx
from mas.elements.llms.common.chat.message import ChatMessage, Role
from mas.elements.llms.openai_compatible.openai_compatible import (
    OpenAICompatibleLLM,
    build_http_client,
)

MESSAGES = [ChatMessage(role=Role.USER, content="hi")]


def _ok(request):
    body = {
        "id": "c1", "object": "chat.completion", "created": 0, "model": "m",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    return httpx.Response(200, json=body)


def _llm(seen, max_tokens=None, headers=None):
    tracing = MagicMock()

    @contextmanager
    def trace_llm(**kw):
        seen.append(kw.get("metadata"))
        yield MagicMock()

    tracing.trace_llm = trace_llm
    forwarder = None
    if headers:
        forwarder = MagicMock()
        forwarder.headers.return_value = dict(headers)
    return OpenAICompatibleLLM(
        base_url="http://llm.test/v1", model_name="m", tracing=tracing, max_tokens=max_tokens, forwarder=forwarder,
        http_client=build_http_client(transport=httpx.MockTransport(_ok)),
    )


def test_the_ceiling_and_the_header_are_in_the_span_metadata():
    seen = []
    _llm(seen, max_tokens=64, headers={"X-Zuno-Max-Tokens": "64"}).chat(MESSAGES)
    assert seen == [{"max_tokens": 64, "x_zuno_max_tokens": "64"}]


def test_no_header_no_entry():
    seen = []
    _llm(seen).chat(MESSAGES)
    assert seen == [{"max_tokens": None}]
