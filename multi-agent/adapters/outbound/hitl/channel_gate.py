"""
Channel-based ApprovalGate adapter.

Emits an ``approval_required`` event through the channel's outbound
path, then blocks on the channel's inbound path (``wait_for``) until
the human responds or the timeout expires.

Works identically for ``LocalInputCapableChannel`` (foreground,
same-process) and ``RedisInputCapableChannel`` (background,
cross-process) — the channel adapter hides the difference.
"""
import logging
from dataclasses import asdict
from typing import Optional

from mas.core.channels import InputCapableChannel
from mas.core.hitl.models import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalResponse,
    HITLConfig,
)
from mas.core.hitl.ports import ApprovalGate

logger = logging.getLogger(__name__)


class ChannelApprovalGate(ApprovalGate):
    """ApprovalGate that uses an InputCapableChannel for transport."""

    def __init__(
        self,
        channel: InputCapableChannel,
        config: HITLConfig,
    ) -> None:
        super().__init__(config)
        self._channel = channel

    def _send_and_wait(
        self,
        request: ApprovalRequest,
        timeout: float,
    ) -> Optional[ApprovalResponse]:
        args_str = str(request.tool_args)
        channel_sid = self._channel.session_id
        logger.info(
            "HITL approval required: tool=%s, access_mode=%s, "
            "origin=%s (%s), session=%s, timeout=%ss",
            request.tool_name,
            request.tool_access_mode.value,
            request.origin.node_display_name,
            request.origin.node_uid,
            channel_sid,
            timeout,
        )
        logger.debug(
            "HITL request_id=%s, args=%s",
            request.request_id,
            args_str,
        )

        self._channel.mark_pending(request.request_id, timeout)
        answered = False
        try:
            raw = self._announce_and_wait(request, timeout)
            answered = raw is not None
        finally:
            self._end_pending(request, answered)
        if raw is None:
            logger.info(
                "HITL timeout: request_id=%s, applying default=%s",
                request.request_id,
                self._config.timeout_decision.value,
            )
            return None
        return self._response(request, raw)

    def _end_pending(self, request: ApprovalRequest, answered: bool) -> None:
        """The wait is over: the request can no longer be answered. Never hides the outcome of the wait itself."""
        try:
            self._channel.clear_pending(request.request_id)
            if not answered:  # timed out or interrupted: tell the clients that still show the request
                self._channel.emit({"type": "approval_expired", "request_id": request.request_id,
                                    "node": request.origin.node_uid})
        except Exception:  # noqa: BLE001
            logger.warning("HITL pending cleanup failed: request_id=%s", request.request_id, exc_info=True)

    def _announce_and_wait(self, request: ApprovalRequest, timeout: float) -> Optional[dict]:
        self._channel.emit({
            "type": "approval_required",
            "node": request.origin.node_uid,
            "display_name": request.origin.node_display_name,
            "request_id": request.request_id,
            "approval_type": request.type.value,
            "origin": asdict(request.origin),
            "tool_name": request.tool_name,
            "tool_args": request.tool_args,
            "tool_description": request.tool_description,
            "tool_access_mode": request.tool_access_mode.value,
            "reasoning": request.reasoning,
        })

        return self._channel.wait_for(request.request_id, timeout=timeout)

    @staticmethod
    def _response(request: ApprovalRequest, raw: dict) -> ApprovalResponse:
        decision = raw.get("decision", "reject")
        logger.info(
            "HITL response: request_id=%s, decision=%s, feedback=%s",
            request.request_id,
            decision,
            raw.get("feedback", ""),
        )

        return ApprovalResponse(
            request_id=request.request_id,
            decision=ApprovalDecision(decision),
            feedback=raw.get("feedback", ""),
            modified_args=raw.get("modified_args", {}),
        )
