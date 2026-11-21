"""R-567: the HITL approval timeout is read from MAS_HITL_TIMEOUT_SECONDS by ChannelApprovalGateFactory.create.

Absent or invalid (not a number, empty, zero, negative) = the historical 300 s, with a warning that names the variable;
a positive number is used as is. The gate and the gate it decorates must carry the same value."""
import logging
from types import SimpleNamespace

import pytest

from outbound.hitl.gate_factory import ChannelApprovalGateFactory
from mas.core.channels import InputCapableChannel
from mas.core.hitl.ports import OverridesStore

ENV = "MAS_HITL_TIMEOUT_SECONDS"


class _Store(OverridesStore):
    def __init__(self):
        self.data = {}

    def load(self, session_id):
        return self.data.get(session_id)

    def save(self, session_id, overrides):
        self.data[session_id] = overrides

    def remove(self, session_id):
        self.data.pop(session_id, None)


_Channel = type("_Channel", (InputCapableChannel,),
                {n: (lambda *a, **k: None) for n in InputCapableChannel.__abstractmethods__})


def _gate():
    gate, _ = ChannelApprovalGateFactory(_Store()).create(_Channel(), SimpleNamespace(hitl_overrides={}), "s1")
    return gate


def _timeouts(gate):
    """Timeout of the gate built by the factory and of the transport gate it wraps."""
    return gate._config.timeout_seconds, gate._inner._config.timeout_seconds


def test_without_the_variable_the_timeout_is_300_seconds(monkeypatch, caplog):
    monkeypatch.delenv(ENV, raising=False)
    with caplog.at_level(logging.WARNING):
        assert _timeouts(_gate()) == (300, 300)
    assert not [r for r in caplog.records if ENV in r.getMessage()]  # nothing to warn about


@pytest.mark.parametrize("value,expected", [("600", 600.0), ("12.5", 12.5), (" 600 ", 600.0)])
def test_a_positive_number_is_used_by_both_gates(monkeypatch, value, expected):
    monkeypatch.setenv(ENV, value)
    outer, inner = _timeouts(_gate())
    assert outer == inner == expected


@pytest.mark.parametrize("value", ["abc", "", "0", "-5", "nan", "inf"])
def test_an_invalid_value_falls_back_to_300_and_the_warning_names_the_variable(monkeypatch, caplog, value):
    monkeypatch.setenv(ENV, value)
    with caplog.at_level(logging.WARNING):
        assert _timeouts(_gate()) == (300, 300)
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING and ENV in r.getMessage()]
    assert len(warnings) == 1
    if value.strip() and value != "0":  # the message names the variable, never the (possibly secret-looking) value
        assert value not in warnings[0].getMessage()


def test_the_value_is_read_at_each_create_not_once_at_import(monkeypatch):
    monkeypatch.setenv(ENV, "600")
    assert _timeouts(_gate()) == (600.0, 600.0)
    monkeypatch.setenv(ENV, "90")
    assert _timeouts(_gate()) == (90.0, 90.0)
