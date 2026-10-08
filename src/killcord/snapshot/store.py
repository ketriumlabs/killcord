"""Crash-safe snapshot store.

Two kinds of state live on disk here, both as plain JSON files anyone can
`cat` (a trust tool must be auditable):

- state.json     — persistent Tripwire counters (spend, action count, rate
                    window). Survives restarts so caps can't be reset by
                    crashing the process. Written on every check().
- pending.json    — the current tripped action, if any: what tripped, why,
                    and (once a human decides) approve/deny. Consumed by an
                    atomic rename to pending.json.consumed-<token> so a
                    second resume attempt can never re-permit the same
                    tripped action — see docs/resume-semantics.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from killcord.core.action import Action
from killcord.snapshot.atomic import atomic_rename, atomic_write_text

DecisionValue = Literal["approved", "denied"]


class NoPendingSnapshotError(Exception):
    """Raised when resume() is called but there's nothing tripped."""


class AlreadyConsumedError(Exception):
    """Raised when resume() is called twice for the same tripped action.

    This is the at-most-once guarantee: the second caller must not be told
    it's safe to proceed.
    """


class PendingSnapshotExistsError(Exception):
    """Raised when a new trip would replace an unresolved pending snapshot."""


class DecisionAlreadyRecordedError(Exception):
    """Raised when a recorded decision is changed to the opposite verdict."""


@dataclass
class CounterState:
    spent: Decimal = Decimal("0")
    action_count: int = 0
    rate_events: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "spent": str(self.spent),
            "action_count": self.action_count,
            "rate_events": self.rate_events,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> CounterState:
        return CounterState(
            spent=Decimal(d.get("spent", "0")),
            action_count=d.get("action_count", 0),
            rate_events=list(d.get("rate_events", [])),
        )


@dataclass
class PendingSnapshot:
    token: str
    action: Action
    reason: str
    tripped_at: float
    trip_id: str = ""
    decision: DecisionValue | None = None
    decided_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "action": self.action.to_dict(),
            "reason": self.reason,
            "tripped_at": self.tripped_at,
            "trip_id": self.trip_id,
            "decision": self.decision,
            "decided_at": self.decided_at,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> PendingSnapshot:
        token = d["token"]
        # Older snapshots only contain the bearer token. Derive a stable,
        # non-secret correlation ID without exposing that token externally.
        trip_id = d.get("trip_id") or hashlib.sha256(token.encode()).hexdigest()[:32]
        return PendingSnapshot(
            token=token,
            action=Action.from_dict(d["action"]),
            reason=d["reason"],
            tripped_at=d["tripped_at"],
            trip_id=trip_id,
            decision=d.get("decision"),
            decided_at=d.get("decided_at"),
        )


@dataclass(frozen=True)
class Decision:
    token: str
    approved: bool
    action: Action
    trip_id: str = ""
    event_at: float = 0.0


class SnapshotStore:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._state_path = self.directory / "state.json"
        self._pending_path = self.directory / "pending.json"
        self._lock_path = self.directory / ".snapshot.lock"

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        """Serialize snapshot transitions across threads and processes."""
        with self._lock_path.open("a+b") as lock_file:
            if lock_file.seek(0, 2) == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            if os.name == "nt":
                import msvcrt

                # getattr keeps mypy portable: the other platform's module is unavailable.
                locking = getattr(msvcrt, "locking")  # noqa: B009
                lock = getattr(msvcrt, "LK_LOCK")  # noqa: B009
                unlock = getattr(msvcrt, "LK_UNLCK")  # noqa: B009
                locking(lock_file.fileno(), lock, 1)
                try:
                    yield
                finally:
                    lock_file.seek(0)
                    locking(lock_file.fileno(), unlock, 1)
            else:
                import fcntl

                flock = getattr(fcntl, "flock")  # noqa: B009
                lock = getattr(fcntl, "LOCK_EX")  # noqa: B009
                unlock = getattr(fcntl, "LOCK_UN")  # noqa: B009
                flock(lock_file.fileno(), lock)
                try:
                    yield
                finally:
                    flock(lock_file.fileno(), unlock)

    # ---- counters -------------------------------------------------------

    def load_state(self) -> CounterState:
        if not self._state_path.exists():
            return CounterState()
        return CounterState.from_dict(json.loads(self._state_path.read_text(encoding="utf-8")))

    def save_state(self, state: CounterState) -> None:
        atomic_write_text(self._state_path, json.dumps(state.to_dict()))

    # ---- trip / pending ---------------------------------------------------

    def write_pending(self, action: Action, reason: str) -> PendingSnapshot:
        with self._exclusive_lock():
            current = self.read_pending()
            if current is not None:
                raise PendingSnapshotExistsError(
                    f"snapshot {current.token!r} is still pending; resolve it before "
                    "recording another trip"
                )
            snapshot = PendingSnapshot(
                token=secrets.token_urlsafe(16),
                action=action,
                reason=reason,
                tripped_at=time.time(),
                trip_id=secrets.token_hex(16),
            )
            atomic_write_text(self._pending_path, json.dumps(snapshot.to_dict()))
        return snapshot

    def read_pending(self) -> PendingSnapshot | None:
        if not self._pending_path.exists():
            return None
        return PendingSnapshot.from_dict(json.loads(self._pending_path.read_text(encoding="utf-8")))

    def decide(self, token: str, approved: bool) -> PendingSnapshot:
        with self._exclusive_lock():
            pending = self.read_pending()
            if pending is None or pending.token != token:
                raise NoPendingSnapshotError(f"no pending snapshot with token {token!r}")
            requested: DecisionValue = "approved" if approved else "denied"
            if pending.decision is not None and pending.decision != requested:
                raise DecisionAlreadyRecordedError(
                    f"snapshot {token!r} already has decision {pending.decision!r}; "
                    "it cannot be changed"
                )
            if pending.decision == requested:
                return pending
            pending.decision = requested
            pending.decided_at = time.time()
            atomic_write_text(self._pending_path, json.dumps(pending.to_dict()))
        return pending

    def resume(self, token: str) -> Decision:
        """Consume the pending snapshot for `token`, exactly once.

        Raises NoPendingSnapshotError if nothing is pending or the decision
        hasn't been made yet. Raises AlreadyConsumedError if this token was
        already resumed — the at-most-once guarantee.
        """
        with self._exclusive_lock():
            consumed_marker = self.directory / f"pending.json.consumed-{token}"
            if consumed_marker.exists():
                raise AlreadyConsumedError(f"snapshot {token!r} was already resumed")

            pending = self.read_pending()
            if pending is None or pending.token != token:
                raise NoPendingSnapshotError(f"no pending snapshot with token {token!r}")
            if pending.decision is None:
                raise NoPendingSnapshotError(f"snapshot {token!r} has no decision yet")

            try:
                atomic_rename(self._pending_path, consumed_marker)
            except FileNotFoundError as exc:
                raise AlreadyConsumedError(f"snapshot {token!r} was already resumed") from exc

            return Decision(
                token=pending.token,
                approved=pending.decision == "approved",
                action=pending.action,
                trip_id=pending.trip_id,
                event_at=pending.decided_at or pending.tripped_at,
            )
