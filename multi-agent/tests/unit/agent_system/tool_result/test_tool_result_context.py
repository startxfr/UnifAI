"""Tool results sent to the model: binary payloads out, size capped, the rest untouched."""
import base64
import json

import pytest

from mas.elements.nodes.common.agent.tool_result_context import tool_output_for_model

pytestmark = pytest.mark.unit

SVG = base64.b64encode(b"<svg>" + b"x" * 40000 + b"</svg>").decode()


def diagram():
    return {"data_base64": SVG, "mime_type": "image/svg+xml", "alt": "Route vs Ingress", "provider": "mermaid"}


def test_binary_payload_becomes_a_marker_for_a_dict():
    text = tool_output_for_model(diagram())
    assert SVG not in text and len(text) < 500
    assert "image/svg+xml" in text and "Route vs Ingress" in text and "mermaid" in text


def test_binary_payload_becomes_a_marker_for_json_text():
    text = tool_output_for_model(json.dumps(diagram()))
    assert SVG not in text and "image/svg+xml" in text


def test_python_repr_loses_its_base64_run():
    text = tool_output_for_model(str(diagram()))
    assert SVG not in text and "mermaid" in text


def test_b64_json_in_a_nested_list():
    text = tool_output_for_model({"data": [{"b64_json": SVG, "mime_type": "image/png"}]})
    assert SVG not in text and "image/png" in text


def test_small_or_plain_results_are_unchanged():
    assert tool_output_for_model({"a": 1}) == str({"a": 1})
    assert tool_output_for_model("hello") == "hello"
    short = {"data_base64": "abc", "mime_type": "image/png"}
    assert tool_output_for_model(short) == str(short)


def test_cap_truncates_with_a_marker(monkeypatch):
    monkeypatch.setenv("MAS_TOOL_RESULT_MAX_TOKENS", "100")
    text = tool_output_for_model("w " * 1000)
    assert text.startswith("w w") and "truncated" in text and len(text) < 600


def test_cap_zero_disables_it(monkeypatch):
    monkeypatch.setenv("MAS_TOOL_RESULT_MAX_TOKENS", "0")
    assert tool_output_for_model("w " * 100000) == "w " * 100000


def test_default_cap_is_8000_tokens(monkeypatch):
    monkeypatch.delenv("MAS_TOOL_RESULT_MAX_TOKENS", raising=False)
    text = tool_output_for_model("w " * 40000)
    assert 32000 <= len(text) < 32200
