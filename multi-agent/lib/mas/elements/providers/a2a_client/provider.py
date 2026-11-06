"""
A2AProvider - High-level interface for A2A communication.

Works with ChatMessage (your system type).
Orchestrates client, converter, and polling.
"""

import asyncio
import logging
import threading
from typing import Callable, Optional, Dict, Any, AsyncIterator, Iterator, Set, Tuple

import anyio
from pydantic import HttpUrl

from a2a.types import AgentCard, TaskState

from global_utils.utils.async_bridge import get_async_bridge

from mas.core.auth.credentials.credential import AuthCredential
from mas.core.auth.errors import AuthError
from mas.elements.llms.common.chat.message import ChatMessage
from mas.elements.providers.a2a_client.client import A2AClient, A2AClientError, A2AConnectionError
from mas.elements.providers.a2a_client.converter import A2AConverter, ConversionResult
from mas.elements.providers.a2a_client.result import A2AResult

logger = logging.getLogger(__name__)

# How long we wait for the remote agent to acknowledge a cancellation.
CANCEL_TIMEOUT_SECONDS = 5.0

# Approvals one delegation may relay (R-535 step 5); beyond that the remote task is cancelled.
MAX_APPROVALS_PER_DELEGATION = 5

# Decides an approval request of the remote agent: (zuno.approval payload) -> (decision, feedback).
# Blocking (it may wait for a human); the provider runs it in a worker thread. v1 sends "approve" or "reject" only.
ApprovalHandler = Callable[[Dict[str, Any]], Tuple[str, str]]


class A2ATaskError(A2AClientError):
    """Task execution error."""

    def __init__(
            self,
            message: str,
            task_id: Optional[str] = None,
            state: Optional[TaskState] = None,
    ):
        super().__init__(message)
        self.task_id = task_id
        self.state = state


class A2AApprovalCapReached(A2ATaskError):
    """The session has used all the approval requests it may relay (R-538): the remote task is cancelled and the
    human is not asked."""


class A2ATimeoutError(A2AClientError):
    """Polling timeout. ``_poll`` fills in what happened to the remote task once we stopped waiting."""

    task_id: Optional[str] = None
    timeout_seconds: Optional[float] = None
    cancelled: Optional[bool] = None  # True: the remote acknowledged tasks/cancel; False: the cancel failed


class A2AProgress:
    """What a caller that may be interrupted can learn about a delegation (filled by ``send_message``).

    ``task_id`` is set once the remote task exists; when the wait is interrupted, ``cancel`` becomes "cancelled" or
    "cancel_failed" and ``settled`` is set once the cleanup (tasks/cancel) has run, which happens on the bridge's
    loop, after the interrupted thread has already left.
    """

    def __init__(self) -> None:
        self.task_id: Optional[str] = None
        self.cancel: Optional[str] = None
        self.settled = threading.Event()


class A2AProvider:
    """
    High-level A2A interface.
    
    Provides ChatMessage-based API over A2A protocol.
    
    Flow:
        ChatMessage → A2A Message → Agent → A2AResult → ChatMessage
    """

    def __init__(
            self,
            base_url: HttpUrl,
            agent_card: Optional[AgentCard] = None,
            headers: Optional[Dict[str, str]] = None,
            auth: Optional[AuthCredential] = None,
    ):
        """
        Initialize provider.
        
        Args:
            base_url: A2A agent URL
            agent_card: Pre-fetched agent card (optional)
            headers: Static HTTP headers (optional; e.g. additional_headers / bearer)
            auth: Optional AuthCredential for live SSO token refresh
        """
        self.base_url = base_url
        self.agent_card = agent_card
        self.headers = headers or {}
        self._auth = auth
        self._converter = A2AConverter()
        self._initialized = False

    def update_headers(self, headers: Dict[str, str]) -> None:
        """Merge new headers (e.g. refreshed auth token) into the provider."""
        self.headers.update(headers)

    async def _get_current_headers(self) -> Dict[str, str]:
        """Merge live auth headers with static headers (static wins on key clash)."""
        current: Dict[str, str] = {}
        if self._auth:
            try:
                current.update(await self._auth.get_headers())
            except AuthError as exc:
                logger.warning(
                    "A2AProvider: auth headers unavailable (%s)",
                    type(exc).__name__,
                )
        if self.headers:
            current.update(self.headers)
        return current

    async def _ensure_initialized(self) -> None:
        """Initialize on first use."""
        if self._initialized:
            return

        async with A2AClient(
                self.base_url,
                agent_card=self.agent_card,
                headers=await self._get_current_headers() or None,
        ) as client:
            self.agent_card = client.agent_card

        self._initialized = True

    async def send_message(
            self,
            message: ChatMessage,
            task_id: Optional[str] = None,
            context_id: Optional[str] = None,
            part_metadata: Optional[Dict[str, Any]] = None,
            wait_for_completion: bool = True,
            raise_on_error: bool = False,
            poll_interval: float = 0.5,
            max_poll_attempts: int = 60,
            blocking: Optional[bool] = None,
            progress: Optional[A2AProgress] = None,
            on_approval: Optional[ApprovalHandler] = None,
    ) -> Tuple[ChatMessage, Dict[str, Any]]:
        """
        Send message and get response.
        
        Args:
            message: ChatMessage to send
            task_id: Optional task ID for multi-turn
            context_id: Optional context ID for multi-turn
            part_metadata: Metadata for message parts.
                          Default: {"type": "user_message"}
                          Pass {} for no metadata.
            wait_for_completion: Wait for task to complete
            raise_on_error: Raise exception on failure (default: return error in message)
            poll_interval: Seconds between polls
            max_poll_attempts: Maximum polling attempts
            blocking: False makes the send return the task at once, so that the polling above (and its bound) is what
                waits for the answer; None keeps the server's default (the request is held until the task is done)
            on_approval: decides the approval requests of the remote agent (input-required with ``zuno.approval``);
                without it every request is rejected (fail closed)
            
        Returns:
            Tuple of (response ChatMessage, metadata dict)
        """
        await self._ensure_initialized()

        async with A2AClient(
                self.base_url,
                agent_card=self.agent_card,
                headers=await self._get_current_headers() or None,
        ) as client:
            a2a_message = self._converter.to_a2a_message(
                message,
                task_id=task_id,
                context_id=context_id,
                part_metadata=part_metadata,
            )

            result = await client.send(a2a_message, blocking=blocking)

            if raise_on_error and result.is_failure:
                raise A2ATaskError(
                    result.error_message or "Task failed",
                    task_id=result.task_id,
                    state=result.state,
                )

            if wait_for_completion and not result.is_complete and not result.is_failure:
                if progress is not None:
                    progress.task_id = result.task_id
                result = await self._await_result(
                    client, result, poll_interval, max_poll_attempts, raise_on_error, progress, on_approval,
                )

            conversion = self._converter.to_chat_message(result)
            return conversion.message, conversion.metadata

    async def _await_result(
            self,
            client: A2AClient,
            result: A2AResult,
            interval: float,
            max_attempts: int,
            raise_on_error: bool,
            progress: Optional[A2AProgress],
            on_approval: Optional[ApprovalHandler],
    ) -> A2AResult:
        """Poll the task to its end, relaying the approval requests of the remote agent on the way (R-535 step 5).

        An input-required task carrying ``zuno.approval`` is answered by a new message on the same task and context,
        then polled again. Authentication required is an error. More than MAX_APPROVALS_PER_DELEGATION requests
        cancel the remote task.
        """
        task_id = result.task_id
        answered: Set[str] = set()
        while True:
            result = await self._poll(client, task_id, interval, max_attempts, raise_on_error, progress, answered)
            if result.requires_auth:
                await self._cancel_remote(client, task_id)
                raise A2ATaskError(
                    "The remote agent requires authentication that the delegation cannot provide",
                    task_id=task_id, state=result.state,
                )
            approval = result.approval if result.requires_input else None
            if approval is None:
                return result
            if len(answered) >= MAX_APPROVALS_PER_DELEGATION:
                await self._cancel_remote(client, task_id)
                raise A2ATaskError(
                    f"The remote agent asked for more than {MAX_APPROVALS_PER_DELEGATION} approvals in one delegation",
                    task_id=task_id, state=result.state,
                )
            request_id = str(approval["request_id"])
            decision, feedback = await self._decide(client, task_id, approval, on_approval, progress)
            answered.add(request_id)
            logger.info("a2a.approval_answered", extra={"task_id": task_id, "request_id": request_id,
                                                        "decision": decision})
            answer = self._converter.to_approval_message(task_id, result.context_id, request_id, decision, feedback)
            result = await client.send(answer, blocking=False)
            if result.is_complete or result.is_failure:
                return result

    async def _decide(
            self,
            client: A2AClient,
            task_id: str,
            approval: Dict[str, Any],
            on_approval: Optional[ApprovalHandler],
            progress: Optional[A2AProgress],
    ) -> Tuple[str, str]:
        """Ask the handler (in a worker thread: it may wait for a human); fail closed on absence or error."""
        if on_approval is None:
            return "reject", "No approval channel is available to the delegating agent"
        try:
            decision, feedback = await asyncio.to_thread(on_approval, approval)
        except A2AApprovalCapReached as e:
            await self._cancel_remote(client, task_id)
            logger.warning("a2a.approval_cap_reached", extra={"task_id": task_id})
            e.task_id = task_id
            raise
        except Exception as e:  # a failing handler must not approve anything
            logger.warning("a2a.approval_handler_failed", extra={"task_id": task_id, "error": f"{type(e).__name__}: {e}"})
            return "reject", "The approval could not be obtained"
        except BaseException:  # interrupted while a human was being asked: stop the remote task
            cancelled = await self._cancel_remote(client, task_id)
            if progress is not None:
                progress.cancel = "cancelled" if cancelled else "cancel_failed"
                progress.settled.set()
            raise
        return ("approve" if decision == "approve" else "reject"), feedback or ""

    async def _poll(
            self,
            client: A2AClient,
            task_id: str,
            interval: float,
            max_attempts: int,
            raise_on_error: bool,
            progress: Optional[A2AProgress] = None,
            answered: Optional[Set[str]] = None,
    ) -> A2AResult:
        """Poll until completion or timeout; the remote task is cancelled when we stop waiting for it (ADR-0406).

        ``answered``: request ids already answered; the task may still show them for a moment, they are not asked again."""
        try:
            return await self._poll_loop(client, task_id, interval, max_attempts, raise_on_error, answered)
        except A2ATaskError:
            raise  # the task ended on its own (failed, input or auth required): nothing left to cancel
        except A2ATimeoutError as e:
            e.task_id = task_id
            e.timeout_seconds = max_attempts * interval
            logger.warning("a2a.timeout", extra={"task_id": task_id, "timeout_seconds": e.timeout_seconds})
            e.cancelled = await self._cancel_remote(client, task_id)
            raise
        except BaseException:
            cancelled = await self._cancel_remote(client, task_id)
            if progress is not None:
                progress.cancel = "cancelled" if cancelled else "cancel_failed"
                progress.settled.set()
            raise

    @staticmethod
    async def _cancel_remote(client: A2AClient, task_id: str) -> bool:
        """Best effort: tell the remote agent we no longer wait for task_id. Never raises; True if it was cancelled."""
        try:
            # Shielded: when we are being cancelled, the scope we run in keeps cancelling every await of this task.
            with anyio.CancelScope(shield=True):
                await asyncio.wait_for(client.cancel_task(task_id), timeout=CANCEL_TIMEOUT_SECONDS)
            logger.info("a2a.task_cancelled", extra={"task_id": task_id})
            return True
        except BaseException as e:  # a second cancellation or a failing gateway must not hide the first error
            logger.warning("a2a.task_cancel_failed", extra={"task_id": task_id, "error": f"{type(e).__name__}: {e}"})
            return False

    async def _poll_loop(
            self,
            client: A2AClient,
            task_id: str,
            interval: float,
            max_attempts: int,
            raise_on_error: bool,
            answered: Optional[Set[str]] = None,
    ) -> A2AResult:
        for _ in range(max_attempts):
            await asyncio.sleep(interval)

            result = await client.get_task(task_id)

            if raise_on_error and result.is_failure:
                raise A2ATaskError(
                    result.error_message or "Task failed",
                    task_id=task_id,
                    state=result.state,
                )

            if result.is_complete:
                return result

            if result.requires_input:
                pending = result.approval
                if pending is not None and str(pending["request_id"]) in (answered or ()):
                    continue  # our answer is not reflected yet
                if raise_on_error and pending is None:
                    raise A2ATaskError("Input required", task_id=task_id, state=result.state)
                return result

            if result.requires_auth:
                if raise_on_error:
                    raise A2ATaskError("Authentication required", task_id=task_id, state=result.state)
                return result

        raise A2ATimeoutError(f"Polling timeout after {max_attempts * interval}s")

    async def stream_message(
            self,
            message: ChatMessage,
            task_id: Optional[str] = None,
            context_id: Optional[str] = None,
            part_metadata: Optional[Dict[str, Any]] = None,
            raise_on_error: bool = False,
    ) -> AsyncIterator[ChatMessage]:
        """
        Stream message and yield responses.
        
        Args:
            message: ChatMessage to send
            task_id: Optional task ID
            context_id: Optional context ID
            part_metadata: Metadata for message parts.
                          Default: {"type": "user_message"}
                          Pass {} for no metadata.
            raise_on_error: Raise on error (default: yield error in message)
            
        Yields:
            ChatMessage for each streaming update with content
        """
        await self._ensure_initialized()

        async with A2AClient(
                self.base_url,
                agent_card=self.agent_card,
                headers=await self._get_current_headers() or None,
        ) as client:
            a2a_message = self._converter.to_a2a_message(
                message,
                task_id=task_id,
                context_id=context_id,
                part_metadata=part_metadata,
            )

            async for result in client.stream(a2a_message):
                if result.is_failure:
                    if raise_on_error:
                        raise A2ATaskError(
                            result.error_message or "Stream error",
                            task_id=result.task_id,
                            state=result.state,
                        )

                conversion = self._converter.to_chat_message(result)
                if conversion.message.content:
                    yield conversion.message

    def send_message_sync(
            self,
            message: ChatMessage,
            **kwargs,
    ) -> Tuple[ChatMessage, Dict[str, Any]]:
        """Sync version of send_message."""
        with get_async_bridge() as bridge:
            return bridge.run(self.send_message(message, **kwargs))

    def stream_message_sync(
            self,
            message: ChatMessage,
            **kwargs,
    ) -> Iterator[ChatMessage]:
        """Sync version of stream_message."""
        with get_async_bridge() as bridge:
            for chunk in bridge.iterate(self.stream_message(message, **kwargs)):
                yield chunk

    async def cancel_task(self, task_id: str) -> Tuple[ChatMessage, Dict[str, Any]]:
        """
        Cancel a running task.
        
        Args:
            task_id: ID of task to cancel
            
        Returns:
            Tuple of (ChatMessage with status, metadata)
        """
        async with A2AClient(
                self.base_url,
                agent_card=self.agent_card,
                headers=await self._get_current_headers() or None,
        ) as client:
            result = await client.cancel_task(task_id)
            conversion = self._converter.to_chat_message(result)
            return conversion.message, conversion.metadata

    def cancel_task_sync(self, task_id: str) -> Tuple[ChatMessage, Dict[str, Any]]:
        """Sync version of cancel_task."""
        with get_async_bridge() as bridge:
            return bridge.run(self.cancel_task(task_id))

    @property
    def skills(self) -> list:
        """Get available skill names."""
        if not self.agent_card or not self.agent_card.skills:
            return []
        return [s.name for s in self.agent_card.skills if s.name]

    @classmethod
    async def create(cls, base_url: HttpUrl, **kwargs) -> "A2AProvider":
        """Create and initialize provider."""
        provider = cls(base_url, **kwargs)
        await provider._ensure_initialized()
        return provider

    @classmethod
    def create_sync(cls, base_url: HttpUrl, **kwargs) -> "A2AProvider":
        """Create and initialize provider (sync)."""
        with get_async_bridge() as bridge:
            return bridge.run(cls.create(base_url, **kwargs))

    def __repr__(self) -> str:
        agent_name = self.agent_card.name if self.agent_card else "unknown"
        return f"A2AProvider(agent='{agent_name}', url='{self.base_url}')"
