"""retrieve_first: a failing retriever stays invisible to the user (the turn goes on without context) but is no longer
invisible to the operator (0.1.75, R-564): an event `retrieve_first.failed` on the current span, whose attribute
`mas.retrieve_first.error` is the exception CLASS (never its message, which may carry a URL or a credential), and the
counter `mas.retrieve_first.failures`."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("opentelemetry.sdk")

from mas.elements.nodes.custom_agent.custom_agent import CustomAgentNode
from opentelemetry import metrics
from opentelemetry.metrics import _internal as metrics_internal
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.util._once import Once

EVENT = "retrieve_first.failed"
ERROR_ATTRIBUTE = "mas.retrieve_first.error"
COUNTER = "mas.retrieve_first.failures"
SECRET = "https://rag.internal/search?token=s3cr3t"


class _RagDown(Exception):
    pass


class _Node(CustomAgentNode):
    uid, display_name = "agent-1", "Agent One"  # plain values instead of the context-backed properties
    workspaces = Mock(get_recent_messages=Mock(return_value=[]))


def _node(retriever):
    node = _Node.__new__(_Node)
    node.retriever, node.retrieve_first = retriever, True
    node.history_enabled, node.history_max_turns, node.history_token_budget = True, None, None
    node._build_agent_results_context = lambda thread_id: None
    return node


def _context(node):
    return node._build_conversation_context(SimpleNamespace(thread_id="t", content="What is the PO status?"))


@pytest.fixture(scope="module")
def reader():
    """One in-memory meter provider for the module, installed as the global one (the counter may be created at import
    or at the first failure: both reach it). Tests read the increase of the counter, not its absolute value."""
    reader = InMemoryMetricReader()
    saved = metrics_internal._METER_PROVIDER, metrics_internal._METER_PROVIDER_SET_ONCE
    metrics_internal._METER_PROVIDER, metrics_internal._METER_PROVIDER_SET_ONCE = None, Once()
    metrics.set_meter_provider(MeterProvider(metric_readers=[reader]))
    yield reader
    metrics_internal._METER_PROVIDER, metrics_internal._METER_PROVIDER_SET_ONCE = saved


@pytest.fixture
def spans():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test"), exporter


def _failures(reader):
    """Sum and attribute sets of the counter."""
    total, attributes = 0, []
    data = reader.get_metrics_data()
    for rm in (data.resource_metrics if data else []):
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                if metric.name == COUNTER:
                    for point in metric.data.data_points:
                        total += point.value
                        attributes.append(dict(point.attributes))
    return total, attributes


def _failing_turn(tracer, error):
    node = _node(Mock(retrieve=Mock(side_effect=error)))
    with tracer.start_as_current_span("turn") as span:
        messages = _context(node)
    return messages, span


def test_a_failing_retriever_leaves_the_prompt_without_context(reader, spans):
    tracer, _ = spans
    messages, _ = _failing_turn(tracer, _RagDown(SECRET))
    assert messages[-1].content == "What is the PO status?"


def test_the_failure_is_an_event_on_the_current_span_with_the_class_only(reader, spans):
    tracer, exporter = spans
    _failing_turn(tracer, _RagDown(SECRET))
    (span,) = exporter.get_finished_spans()
    events = [e for e in span.events if e.name == EVENT]
    assert len(events) == 1
    assert events[0].attributes[ERROR_ATTRIBUTE] == "_RagDown"
    # never the message: not in the event, nor anywhere on the span
    dumped = repr([(e.name, dict(e.attributes)) for e in span.events]) + repr(dict(span.attributes))
    assert "s3cr3t" not in dumped and SECRET not in dumped


def test_the_class_name_is_the_exception_type_not_a_fixed_label(reader, spans):
    tracer, exporter = spans
    _failing_turn(tracer, ConnectionError("boom"))
    (span,) = exporter.get_finished_spans()
    assert [e.attributes[ERROR_ATTRIBUTE] for e in span.events if e.name == EVENT] == ["ConnectionError"]


def test_the_failure_counter_goes_up_by_one_per_failure_without_the_message(reader, spans):
    tracer, _ = spans
    before, _ = _failures(reader)
    _failing_turn(tracer, _RagDown(SECRET))
    after, attributes = _failures(reader)
    assert after == before + 1
    assert attributes == [{"mas.node.uid": "agent-1"}]  # the node only: no exception text, no query, no user content
    _failing_turn(tracer, _RagDown(SECRET))
    assert _failures(reader)[0] == before + 2


def test_a_successful_retrieval_records_nothing(reader, spans):
    tracer, exporter = spans
    before, _ = _failures(reader)
    node = _node(Mock(retrieve=Mock(return_value="PAGE: Acme renewal PO received")))
    with tracer.start_as_current_span("turn"):
        messages = _context(node)
    assert messages[-1].content.startswith("context: PAGE")
    (span,) = exporter.get_finished_spans()
    assert [e for e in span.events if e.name == EVENT] == []
    assert _failures(reader)[0] == before


def test_without_a_recording_span_the_failure_still_does_not_fail_the_turn(reader):
    messages = _context(_node(Mock(retrieve=Mock(side_effect=_RagDown(SECRET)))))
    assert messages[-1].content == "What is the PO status?"
