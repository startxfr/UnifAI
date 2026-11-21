"""
Concrete ApprovalGateFactory — adapter that assembles the HITL gate stack.

Creates a ``ChannelApprovalGate`` (transport layer) wrapped in an
``AutoResolvingApprovalGate`` (auto-rule decorator) that reads rules
from the shared ``OverridesStore``.

Both foreground and background runners receive this factory via DI
so the domain layer never imports adapter classes.

On ``create()``, initial overrides are loaded from session metadata
and seeded into the ``OverridesStore`` so the gate has a warm cache.
On ``remove()``, the store entry is cleaned up.

The approval timeout comes from ``MAS_HITL_TIMEOUT_SECONDS`` (R-567), read at
each ``create()`` so a changed environment applies after a restart.
"""
import logging
import math
import os
from typing import Any, Optional

from mas.core.channels import InputCapableChannel
from mas.core.hitl.models import (
    ApprovalOverrides,
    HITLConfig,
    ToolApprovalPolicy,
)
from mas.core.hitl.ports import ApprovalGate, ApprovalGateFactory, OverridesStore
from .auto_resolving_gate import AutoResolvingApprovalGate
from .channel_gate import ChannelApprovalGate

logger = logging.getLogger(__name__)

HITL_TIMEOUT_ENV = "MAS_HITL_TIMEOUT_SECONDS"
DEFAULT_HITL_TIMEOUT_SECONDS = HITLConfig.timeout_seconds  # 300 s


def hitl_timeout_seconds() -> float:
    """Seconds a human has to answer an approval request: ``MAS_HITL_TIMEOUT_SECONDS``, a finite number > 0.

    Absent: the default (300 s). Empty, not a number, <= 0, nan or inf: the default, with a warning that names the
    variable but never its value (an env value may be anything, a mistyped secret included).
    """
    raw = os.environ.get(HITL_TIMEOUT_ENV)
    if raw is None:
        return DEFAULT_HITL_TIMEOUT_SECONDS
    try:
        value = float(raw.strip())
    except ValueError:
        value = math.nan
    if not (math.isfinite(value) and value > 0):
        logger.warning("%s is not a positive number of seconds: using the default %gs",
                       HITL_TIMEOUT_ENV, DEFAULT_HITL_TIMEOUT_SECONDS)
        return DEFAULT_HITL_TIMEOUT_SECONDS
    return value


class ChannelApprovalGateFactory(ApprovalGateFactory):
    """Builds a channel-backed gate with auto-resolving decorator.

    Uses a shared ``OverridesStore`` (Redis-backed) so that rule
    updates from the API endpoint are visible to gates in any
    process — foreground Flask threads or Temporal workers.
    """

    def __init__(self, overrides_store: OverridesStore) -> None:
        self._overrides_store = overrides_store

    @property
    def overrides_store(self) -> OverridesStore:
        return self._overrides_store

    def create(
        self,
        channel: Any,
        session_metadata: Any,
        run_id: str,
    ) -> tuple[Optional[ApprovalGate], Optional[ToolApprovalPolicy]]:
        if not isinstance(channel, InputCapableChannel):
            return None, None

        config = HITLConfig(enabled=True, timeout_seconds=hitl_timeout_seconds())
        inner_gate = ChannelApprovalGate(channel=channel, config=config)

        raw_overrides = getattr(session_metadata, "hitl_overrides", None) or {}
        overrides = ApprovalOverrides.from_dict(raw_overrides)
        self._overrides_store.save(run_id, overrides)

        gate = AutoResolvingApprovalGate(
            inner=inner_gate,
            overrides_store=self._overrides_store,
            session_id=run_id,
            config=config,
        )
        policy = ToolApprovalPolicy()

        logger.info(
            "HITL gate created: run_id=%s, timeout=%ss, default=%s, overrides=%s",
            run_id,
            config.timeout_seconds,
            config.timeout_decision.value,
            overrides.to_dict(),
        )

        return gate, policy

    def remove(self, run_id: str) -> None:
        """Clean up the overrides store entry after a run completes."""
        self._overrides_store.remove(run_id)
