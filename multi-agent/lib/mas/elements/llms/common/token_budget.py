"""Token ceiling of one turn (R-543).

A *turn* is one ``user.session.submit``: it gets a new engine handle, shared by every node activity of that run. The
tokens the model endpoint reports for each call are added to a counter keyed by that turn; a node whose task declares
``max_tokens_per_turn`` refuses its next model call once the counter reaches the ceiling, and the turn ends with the
notice as the answer (the path of a rate limit, not a crash). Unset = no ceiling, no counting cost beyond one add.

The store is shared between processes (Redis) because the nodes of a turn run in different worker activities; the
in-memory one serves a single process (tests, local runs).
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from contextvars import ContextVar
from typing import Optional

from .exceptions import LLMRateLimitError

TOKEN_CEILING_TYPE = "token_ceiling"


class TokenCeilingReached(LLMRateLimitError):
    """The turn used its token ceiling: not a crash, the turn ends cleanly with this notice."""

    def __init__(self, used: int, cap: int) -> None:
        self.used, self.cap = used, cap
        super().__init__(f"Token ceiling reached for this turn ({used}/{cap} tokens)")

    def user_message(self) -> str:
        return self.detail

    def to_dict(self):
        return {"type": TOKEN_CEILING_TYPE, "message": self.detail, "retry_after": None, "used": self.used, "cap": self.cap}


class TokenBudgetStore(ABC):
    @abstractmethod
    def add(self, turn_key: str, tokens: int) -> int:
        """Add *tokens* to the turn and return its new total."""

    @abstractmethod
    def used(self, turn_key: str) -> int:
        """Tokens counted so far for the turn (0 when none)."""

    def announce_once(self, turn_key: str) -> bool:
        """True the first time it is asked for a turn: the ceiling event is emitted once. Per process by default."""
        with _lock:
            if turn_key in _announced:
                return False
            _announced.add(turn_key)
            return True


_lock = threading.Lock()
_announced: set[str] = set()


class InMemoryTokenBudgetStore(TokenBudgetStore):
    def __init__(self) -> None:
        self._data: dict[str, int] = {}

    def add(self, turn_key: str, tokens: int) -> int:
        with _lock:
            self._data[turn_key] = self._data.get(turn_key, 0) + max(0, int(tokens))
            return self._data[turn_key]

    def used(self, turn_key: str) -> int:
        with _lock:
            return self._data.get(turn_key, 0)


_store: TokenBudgetStore = InMemoryTokenBudgetStore()
_turn_key: ContextVar[Optional[str]] = ContextVar("mas_turn_key", default=None)


def configure(store: TokenBudgetStore) -> None:
    """Install the process-wide store (the container does it once, Redis when there is one)."""
    global _store
    _store = store


def bind_turn(session_id: Optional[str], engine_handle: Optional[str]) -> None:
    """Bind the turn of the current activity (always overwrites: a reused worker thread must not leak a turn)."""
    _turn_key.set(f"{session_id}:{engine_handle or ''}" if session_id else None)


def current_turn() -> Optional[str]:
    return _turn_key.get()


def check(cap: Optional[int]) -> None:
    """Raise ``TokenCeilingReached`` when the current turn already used *cap* tokens (no turn or no cap: nothing)."""
    key = _turn_key.get()
    if not cap or not key:
        return
    used = _store.used(key)
    if used >= cap:
        raise TokenCeilingReached(used, cap)


def record(tokens: Optional[int], cap: Optional[int] = None) -> None:
    """Count the tokens of a model call against the current turn (only when a ceiling applies)."""
    key = _turn_key.get()
    if not cap or not key or not tokens:
        return
    _store.add(key, tokens)


def announce_once() -> bool:
    """True for the first node of the current turn that reports the ceiling: the event is emitted once per turn."""
    key = _turn_key.get()
    return _store.announce_once(key) if key else True
