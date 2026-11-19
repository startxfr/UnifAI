"""R-558: the status updates of a streamed A2A task are not part of the answer.

A status update without text ("submitted", "working") used to become the content "Task status: <state>" and the
caller, which concatenates the chunks, put "Task status: submittedTask status: working" in front of the real answer.
"""

import asyncio

import pytest
from a2a.types import (
    Artifact, Part, Task, TaskArtifactUpdateEvent, TaskState, TaskStatus, TaskStatusUpdateEvent, TextPart,
)
from mas.elements.providers.a2a_client import provider as provider_module
from mas.elements.providers.a2a_client.converter import A2AConverter
from mas.elements.providers.a2a_client.provider import A2AProvider
from mas.elements.providers.a2a_client.result import A2AResult, ResultKind
from mas.elements.llms.common.chat.message import ChatMessage, Role


def _task(state):
    return A2AResult(kind=ResultKind.TASK, task=Task(id="t1", context_id="c1", status=TaskStatus(state=state)))


def _status(state, final=False):
    event = TaskStatusUpdateEvent(task_id="t1", context_id="c1", status=TaskStatus(state=state), final=final)
    return A2AResult(kind=ResultKind.STATUS_EVENT, status_event=event)


def _text(text):
    artifact = Artifact(artifact_id="a1", parts=[Part(root=TextPart(text=text))])
    event = TaskArtifactUpdateEvent(task_id="t1", context_id="c1", artifact=artifact)
    return A2AResult(kind=ResultKind.ARTIFACT_EVENT, artifact_event=event)


class _Client:
    def __init__(self, results):
        self.results = results

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def stream(self, message):
        for result in self.results:
            yield result


def _stream(results, monkeypatch):
    provider = A2AProvider.__new__(A2AProvider)
    provider._converter = A2AConverter()
    provider.base_url, provider.agent_card = "http://remote", None

    async def _ready():
        return None

    async def _headers():
        return {}

    provider._ensure_initialized, provider._get_current_headers = _ready, _headers
    monkeypatch.setattr(provider_module, "A2AClient", lambda *a, **k: _Client(results))

    async def _collect():
        return [m.content async for m in provider.stream_message(ChatMessage(role=Role.USER, content="hi"))]

    return asyncio.run(_collect())


def test_status_updates_without_text_are_not_yielded(monkeypatch):
    chunks = _stream([_task(TaskState.submitted), _status(TaskState.working), _text("The answer."),
                      _status(TaskState.completed, final=True)], monkeypatch)
    assert chunks == ["The answer."]
    assert "Task status" not in "".join(chunks)


@pytest.mark.parametrize("state, expected", [
    (TaskState.input_required, "Additional input is required to continue."),
    (TaskState.auth_required, "Authentication is required to continue."),
    (TaskState.canceled, "Task was canceled."),
])
def test_informative_states_keep_their_text(state, expected, monkeypatch):
    assert _stream([_status(state)], monkeypatch) == [expected]


@pytest.mark.parametrize("state, status_only", [
    (TaskState.submitted, True),
    (TaskState.working, True),
    (TaskState.completed, True),
    (TaskState.input_required, False),
    (TaskState.canceled, False),
])
def test_the_converter_flags_a_status_without_text(state, status_only):
    conversion = A2AConverter().to_chat_message(_status(state))
    assert conversion.status_only is status_only
    assert conversion.message.content  # the fallback text stays for the callers that wait for the final result


def test_a_message_with_text_is_never_status_only():
    assert A2AConverter().to_chat_message(_text("The answer.")).status_only is False
