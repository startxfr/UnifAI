"""R-539: the auto-approval rules set through the API must reach the gate built for every node activity."""

from types import SimpleNamespace

import pytest

from outbound.hitl.gate_factory import ChannelApprovalGateFactory
from mas.core.channels import InputCapableChannel
from mas.core.hitl.models import ApprovalOverrides, ApprovalRuleSet
from mas.core.hitl.ports import OverridesStore


class _Store(OverridesStore):
    def __init__(self):
        self.data = {}

    def load(self, session_id):
        return self.data.get(session_id, ApprovalOverrides())

    def save(self, session_id, overrides):
        self.data[session_id] = overrides

    def remove(self, session_id):
        self.data.pop(session_id, None)


_Channel = type("_Channel", (InputCapableChannel,), {n: (lambda *a, **k: None) for n in InputCapableChannel.__abstractmethods__})


def _meta():
    rules = ApprovalOverrides(global_rules=ApprovalRuleSet(approve_all=True))
    return SimpleNamespace(hitl_overrides=rules.to_dict())


def test_a_gate_built_with_the_session_metadata_carries_the_rules_and_without_it_none():
    store = _Store()
    factory = ChannelApprovalGateFactory(store)
    factory.create(_Channel(), _meta(), "s1")
    assert store.load("s1").global_rules.approve_all is True
    factory.remove("s1")  # done after every node activity: the metadata is the source of the rules
    factory.create(_Channel(), None, "s1")
    assert store.load("s1").global_rules.approve_all is False


def test_every_node_activity_builds_its_gate_from_the_session_metadata():
    pytest.importorskip("temporalio")
    from inbound.temporal.activities.graph_node_activities import GraphNodeActivities

    seen = []

    class _Factory:
        def create(self, channel, session_metadata, run_id):
            seen.append(session_metadata)
            return "gate", "policy"

    class _Channels:
        def create_input_capable(self, session_id):
            return object()

    meta = _meta()
    activities = GraphNodeActivities(node_executor=None, channel_factory=_Channels(), gate_factory=_Factory(),
                                     session_meta_loader=lambda sid: meta)
    assert activities._build_bindings("s1").approval_gate == "gate" and seen == [meta]

    def broken(_sid):
        raise RuntimeError("mongo down")

    activities = GraphNodeActivities(node_executor=None, channel_factory=_Channels(), gate_factory=_Factory(),
                                     session_meta_loader=broken)
    activities._build_bindings("s1")
    assert seen[-1] is None  # no rule: the human is asked
