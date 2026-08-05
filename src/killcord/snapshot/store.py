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

import json
import secrets
import time
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
    decision: DecisionValue | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "action": self.action.to_dict(),
            "reason": self.reason,
            "tripped_at": self.tripped_at,
            "decision": self.decision,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> PendingSnapshot:
        return PendingSnapshot(
            token=d["token"],
            action=Action.from_dict(d["action"]),
            reason=d["reason"],
            tripped_at=d["tripped_at"],
            decision=d.get("decision"),
        )


@dataclass(frozen=True)
class Decision:
    token: str
    approved: bool
    action: Action


class SnapshotStore:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._state_path = self.directory / "state.json"
        self._pending_path = self.directory / "pending.json"

    # ---- counters -------------------------------------------------------

    def load_state(self) -> CounterState:
        if not self._state_path.exists():
            return CounterState()
        return CounterState.from_dict(json.loads(self._state_path.read_text(encoding="utf-8")))

    def save_state(self, state: CounterState) -> None:
        atomic_write_text(self._state_path, json.dumps(state.to_dict()))

    # ---- trip / pending ---------------------------------------------------

    def write_pending(self, action: Action, reason: str) -> PendingSnapshot:
        snapshot = PendingSnapshot(
            token=secrets.token_urlsafe(16),
            action=action,
            reason=reason,
            tripped_at=time.time(),
        )
        atomic_write_text(self._pending_path, json.dumps(snapshot.to_dict()))
        return snapshot

    def read_pending(self) -> PendingSnapshot | None:
        if not self._pending_path.exists():
            return None
        return PendingSnapshot.from_dict(json.loads(self._pending_path.read_text(encoding="utf-8")))

    def decide(self, token: str, approved: bool) -> PendingSnapshot:
        pending = self.read_pending()
        if pending is None or pending.token != token:
            raise NoPendingSnapshotError(f"no pending snapshot with token {token!r}")
        pending.decision = "approved" if approved else "denied"
        atomic_write_text(self._pending_path, json.dumps(pending.to_dict()))
        return pending

    def resume(self, token: str) -> Decision:
        """Consume the pending snapshot for `token`, exactly once.

        Raises NoPendingSnapshotError if nothing is pending or the decision
        hasn't been made yet. Raises AlreadyConsumedError if this token was
        already resumed — the at-most-once guarantee.
        """
        consumed_marker = self.directory / f"pending.json.consumed-{token}"
        if consumed_marker.exists():
            raise AlreadyConsumedError(f"snapshot {token!r} was already resumed")

        pending = self.read_pending()
        if pending is None or pending.token != token:
            raise NoPendingSnapshotError(f"no pending snapshot with token {token!r}")
        if pending.decision is None:
            raise NoPendingSnapshotError(f"snapshot {token!r} has no decision yet")

        # The atomic rename is the linearization point: whichever caller's
        # rename wins is the only one that gets a Decision back. A truly
        # concurrent second caller's rename raises FileNotFoundError (source
        # already moved) — treat that the same as the consumed-marker check
        # above, since that's exactly what it means.
        try:
            atomic_rename(self._pending_path, consumed_marker)
        except FileNotFoundError as exc:
            raise AlreadyConsumedError(f"snapshot {token!r} was already resumed") from exc

        return Decision(
            token=pending.token,
            approved=pending.decision == "approved",
            action=pending.action,
        )
