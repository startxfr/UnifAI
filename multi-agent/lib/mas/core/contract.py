"""Names of the contract between multiagent and the gateways it calls.

Headers are ``X-<Namespace>-<Name>`` (the operator writes them into the LLM, MCP and A2A configs it emits for an
UnifaiAgentBundle; multiagent recognises some of them) and A2A metadata keys are ``<namespace>.<name>``.
``UNIFAI_CONTRACT_NAMESPACE`` (UnifaiStack ``spec.contractNamespace``) picks the namespace. Unset, multiagent sends
and accepts both ``unifai`` and ``zuno`` until 0.2, then ``unifai`` only.
"""
from __future__ import annotations

import os

ENV = "UNIFAI_CONTRACT_NAMESPACE"
DEFAULT_NAMESPACES = ("unifai", "zuno")


def namespaces() -> tuple[str, ...]:
    """The contract namespaces in force, the configured one or the defaults."""
    namespace = os.environ.get(ENV, "").strip().lower()
    return (namespace,) if namespace else DEFAULT_NAMESPACES


def header_names(name: str) -> frozenset[str]:
    """The lower-case header names of ``name`` (e.g. ``data-classification``) under every namespace in force."""
    return frozenset(f"x-{namespace}-{name.lower()}" for namespace in namespaces())


def metadata_keys(name: str) -> tuple[str, ...]:
    """The A2A metadata keys of ``name`` (e.g. ``approval``) under every namespace in force, in order."""
    return tuple(f"{namespace}.{name}" for namespace in namespaces())
