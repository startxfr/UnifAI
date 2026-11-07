"""
Temporal activity wrapper for graph node and condition execution.

Composes a channel from the factory (adapter wiring) and delegates
the actual execution to the domain-level NodeExecutor.

Builds a ``NodeRuntimeBindings`` value object (channel + HITL) and
passes it to the executor, which uses ``NodeRuntimeBinder`` to
inject capabilities via protocol checks.

The @heartbeat decorator sends periodic heartbeats while the sync
activity body runs.  Cancellation is handled at the workflow level.

pydantic_data_converter handles GraphState serialization/deserialization
automatically — no manual .serialize()/.deserialize() calls needed.
"""
import logging
from typing import Any, Callable, Optional

from temporalio import activity
from temporalio.exceptions import ApplicationError

from mas.elements.llms.common import token_budget
from mas.core.channels import ChannelFactory
from mas.core.hitl.ports import ApprovalGateFactory
from mas.core.runtime_binder import NodeRuntimeBindings
from mas.engine.distributed.node_executor import NodeExecutor
from mas.graph.state.graph_state import GraphState
from mas.session.domain.exceptions import SessionBuildError
from global_utils.utils.logging_config import bind_correlation_ids
from inbound.temporal.activities.heartbeat import heartbeat
from temporal.models import ExecuteNodeParams, EvaluateConditionParams

logger = logging.getLogger(__name__)


class GraphNodeActivities:
    """
    Thin adapter — composes a channel from the factory (wiring)
    and delegates node execution to the domain NodeExecutor.

    Builds a ``NodeRuntimeBindings`` that carries the channel and
    HITL gate/policy (when available) as a single value object.
    Gate construction is delegated to ``ApprovalGateFactory``.
    """

    def __init__(
        self,
        node_executor: NodeExecutor,
        channel_factory: Optional[ChannelFactory] = None,
        gate_factory: Optional[ApprovalGateFactory] = None,
        session_meta_loader: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self._executor = node_executor
        self._channel_factory = channel_factory
        self._gate_factory = gate_factory
        self._session_meta_loader = session_meta_loader

    @activity.defn(name="execute_graph_node")
    @heartbeat(interval=3)
    def execute_node(self, params: ExecuteNodeParams) -> GraphState:
        bind_correlation_ids(params.request_id, params.session_id)
        token_budget.bind_turn(params.session_id, getattr(params.execution_context, "engine_handle", None))
        bindings = self._build_bindings(params.session_id)
        try:
            return self._executor.execute_node(
                node_uid=params.node_uid,
                node_blueprint=params.node_blueprint,
                step_context=params.step_context,
                state=params.state,
                bindings=bindings,
                execution_context=params.execution_context,
            )
        except SessionBuildError as e:
            raise _as_non_retryable(e) from None
        finally:
            if self._gate_factory is not None:
                self._gate_factory.remove(params.session_id)

    @activity.defn(name="evaluate_condition")
    def evaluate_condition(self, params: EvaluateConditionParams) -> str:
        bind_correlation_ids(params.request_id)
        try:
            return self._executor.evaluate_condition(
                condition_rid=params.condition_rid,
                condition_blueprint=params.condition_blueprint,
                step_context=params.step_context,
                state=params.state,
            )
        except SessionBuildError as e:
            raise _as_non_retryable(e) from None

    # ── Bindings construction ────────────────────────────────────

    def _load_session_meta(self, session_id: str) -> Any:
        """The session metadata, which carries the auto-approval rules set through the API (R-539). The gate is
        rebuilt for every node activity and seeded from it: without it every activity starts with no rule. A failure
        means no rule, so the human is asked."""
        if self._session_meta_loader is None:
            return None
        try:
            return self._session_meta_loader(session_id)
        except Exception:  # noqa: BLE001
            logger.warning("Session metadata unavailable for the HITL gate: session=%s", session_id, exc_info=True)
            return None

    def _build_bindings(self, session_id: str) -> Optional[NodeRuntimeBindings]:
        """Build a ``NodeRuntimeBindings`` from the channel factory.

        Returns ``None`` when no channel factory is configured.
        """
        if not self._channel_factory or not session_id:
            return None

        gate = None
        policy = None

        channel = self._channel_factory.create_input_capable(session_id)
        if channel is not None:
            if self._gate_factory is not None:
                gate, policy = self._gate_factory.create(
                    channel=channel,
                    session_metadata=self._load_session_meta(session_id),
                    run_id=session_id,
                )
        else:
            channel = self._channel_factory.create(session_id)

        return NodeRuntimeBindings(
            channel=channel,
            approval_gate=gate,
            approval_policy=policy,
        )


def _as_non_retryable(e: SessionBuildError) -> ApplicationError:
    """A build failure is deterministic: retrying the activity cannot fix it.

    Raised ``from None`` so the original exception (whose text may hold config)
    is not serialised into the Temporal failure chain.

    Only the secret-free message crosses the Temporal boundary; the workflow
    recognises ``type`` to record it on the session.
    """
    return ApplicationError(e.message, type=SessionBuildError.error_type, non_retryable=True)
