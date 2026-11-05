from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, ConfigDict, model_validator

from mas.core.identity import Identity

# Session staging (SessionInputProjector) sets this tag so OAuth (e.g. Google MCP) looks up
# tokens for the acting human while ``identity`` remains the team (or other owner).
CREDENTIAL_USER_ID_TAG = "credential_user_id"

HITL_ENABLED_TAG = "hitl_enabled"

# Session metadata tags mirrored at staging (see ``with_session_tags``).
SESSION_TAGS_TAG = "session_tags"

# Floor of the run's data classification, raised when a delegated agent answers at a higher level (monotone, never lowered).
RUN_CLASSIFICATION_TAG = "run_classification"
_LEVEL = re.compile(r"^C([1-9])$")


def classification_rank(level: Optional[str]) -> int:
    """C1..C9 -> 1..9; anything else (missing, malformed) -> 0, which raises nothing."""
    match = _LEVEL.match(str(level or "").strip().upper())
    return int(match.group(1)) if match else 0


class ExecutionContext(BaseModel):
    """Runtime execution context — who, what scope, when.

    Immutable (frozen) so mutations go through explicit copy methods.
    ``extra="ignore"`` ensures backward compatibility when deserializing
    older DB documents that carried fields no longer present.
    """

    session_id: str = ""
    identity: Identity
    scope: str = "public"
    engine_name: str = ""
    engine_handle: Optional[str] = None

    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_active_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    tags: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(frozen=True, extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _backfill_identity(cls, values: Any) -> Any:
        """Legacy docs stored without identity — synthesize a placeholder."""
        if isinstance(values, dict) and values.get("identity") is None:
            values["identity"] = {
                "type": "user", "id": "unknown",
                "display_name": "unknown",
            }
        return values

    @property
    def identity_id(self) -> str:
        return self.identity.id

    def with_scope(self, scope: str) -> ExecutionContext:
        return self.model_copy(update={"scope": scope})

    def with_credential_user(self, credential_user_id: str = "") -> ExecutionContext:
        """Copy with per-user OAuth key in ``tags`` (used when ``identity`` is a team).

        A team id is never a valid OAuth credential user, so passing the team's
        own id is silently ignored — callers do not need to pre-filter.
        """
        cu = (credential_user_id or "").strip()
        if not cu or (self.identity.is_team and cu == self.identity.id):
            return self
        tags = dict(self.tags or {})
        tags[CREDENTIAL_USER_ID_TAG] = cu
        return self.model_copy(update={"tags": tags})

    def credential_user_id(self) -> str:
        """Return the credential user id for OAuth lookups.

        For individual sessions this is the identity id.  For team sessions
        the per-member credential user is stored in ``tags``; if absent (e.g.
        the session was not submitted via the HTTP layer) the caller will
        receive an empty string and must handle the missing-credential case.
        """
        cu = (self.tags or {}).get(CREDENTIAL_USER_ID_TAG, "")
        if cu:
            return str(cu).strip()
        if self.identity.is_team:
            return ""
        return self.identity.id

    def with_session_tags(self, session_tags: Optional[Dict[str, Any]]) -> ExecutionContext:
        """Copy with the session's metadata tags mirrored into ``tags``.

        Stamped during staging so elements can reference them (e.g. header
        templates ``{tag.<key>}``) without reading the session record.
        """
        tags = dict(self.tags or {})
        tags[SESSION_TAGS_TAG] = {str(k): str(v) for k, v in (session_tags or {}).items()}
        return self.model_copy(update={"tags": tags})

    def with_hitl(self, enabled: bool) -> ExecutionContext:
        """Copy with the HITL-enabled flag in ``tags``.

        Stamped from ``SessionMeta.hitl_enabled`` during staging so that
        nodes configured with ``HITLMode.DYNAMIC`` can read it at runtime.
        """
        tags = dict(self.tags or {})
        tags[HITL_ENABLED_TAG] = enabled
        return self.model_copy(update={"tags": tags})

    @property
    def hitl_enabled(self) -> bool:
        """Whether dynamic HITL is active (sourced from session metadata)."""
        return bool((self.tags or {}).get(HITL_ENABLED_TAG, False))

    def mark_active(self) -> ExecutionContext:
        return self.model_copy(update={"last_active_at": datetime.now(timezone.utc)})

    def mark_finished(self) -> ExecutionContext:
        now = datetime.now(timezone.utc)
        return self.model_copy(update={"finished_at": now, "last_active_at": now})


class ExecutionContextHolder:
    """Mutable reference to an immutable ExecutionContext.

    Created at build time (uninitialised).  Filled at execution time
    (real values).  Elements receive a closure over this object — they
    read current values when they need them.

    Fail-fast: accessing ``context``, ``scope``, or ``identity_id`` before
    the holder is filled raises ``RuntimeError`` instead of returning
    silent defaults.
    """

    __slots__ = ("_ctx", "_lock")

    def __init__(self) -> None:
        self._ctx: Optional[ExecutionContext] = None
        self._lock = threading.Lock()

    @property
    def context(self) -> ExecutionContext:
        if self._ctx is None:
            raise RuntimeError(
                "ExecutionContext not initialised — "
                "ensure lifecycle.begin() runs before element execution"
            )
        return self._ctx

    @context.setter
    def context(self, value: ExecutionContext) -> None:
        self._ctx = value

    def run_classification(self) -> str:
        """The floor the run was raised to ("" when never raised or not initialised)."""
        return str(((self._ctx.tags if self._ctx else None) or {}).get(RUN_CLASSIFICATION_TAG) or "")

    def raise_classification(self, level: Optional[str]) -> bool:
        """Raise the run's classification floor to ``level`` if it is higher; True when it was raised."""
        wanted = classification_rank(level)
        with self._lock:
            if self._ctx is None or wanted <= classification_rank(self.run_classification()):
                return False
            tags = dict(self._ctx.tags or {})
            tags[RUN_CLASSIFICATION_TAG] = str(level).strip().upper()
            self._ctx = self._ctx.model_copy(update={"tags": tags})
            return True

    @property
    def scope(self) -> str:
        return self.context.scope

    @property
    def identity_id(self) -> str:
        return self.context.identity_id

    @property
    def identity(self) -> Identity:
        return self.context.identity
