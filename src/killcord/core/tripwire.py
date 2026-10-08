"""Tripwire: declarative limits (spend/action/rate/allowlist) plus the
trip -> snapshot -> review -> resume lifecycle.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

from killcord.core.action import Action
from killcord.core.rate import Rate
from killcord.snapshot.store import Decision, SnapshotStore

P = ParamSpec("P")
R = TypeVar("R")


class TripwireTripped(Exception):
    """Raised when an Action violates a Tripwire's limits.

    The pending action was already snapshotted to disk before this was
    raised — see `snapshot_id` and the pause server / `killcord resume`.
    """

    def __init__(self, snapshot_id: str, reason: str, action: Action) -> None:
        self.snapshot_id = snapshot_id
        self.reason = reason
        self.action = action
        super().__init__(f"{reason} (snapshot {snapshot_id}) — run `killcord resume {snapshot_id}`")


class Tripwire:
    def __init__(
        self,
        *,
        max_spend: Decimal | None = None,
        max_actions: int | None = None,
        rate: Rate | None = None,
        allow_domains: list[str] | None = None,
        allow_tools: list[str] | None = None,
        store: str | Path = "~/.killcord/default",
        notify: str | None = None,
        ledger: Any | None = None,
    ) -> None:
        self.max_spend = max_spend
        self.max_actions = max_actions
        self.rate = rate
        self.allow_domains = allow_domains
        self.allow_tools = allow_tools
        self.notify_target = notify
        self.ledger = ledger

        self.store = SnapshotStore(Path(store).expanduser())
        self._state = self.store.load_state()

    def __enter__(self) -> Tripwire:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    # ---- allowlist checks -------------------------------------------------

    def _domain_allowed(self, domain: str | None) -> bool:
        if self.allow_domains is None:
            return True
        if domain is None:
            return False
        for pattern in self.allow_domains:
            if pattern.startswith("*."):
                if domain == pattern[2:] or domain.endswith("." + pattern[2:]):
                    return True
            elif domain == pattern:
                return True
        return False

    def _tool_allowed(self, tool: str) -> bool:
        if self.allow_tools is None:
            return True
        return tool in self.allow_tools

    def _reason_for_trip(self, action: Action, now: float) -> str | None:
        if not self._tool_allowed(action.tool):
            return f"tool {action.tool!r} is not in the allowlist"
        domain = action.domain()
        if action.target is not None and not self._domain_allowed(domain):
            return f"target {action.target!r} is not in the allowed domains"
        if self.rate is not None:
            window_start = self.rate.window_start(now)
            recent = [t for t in self._state.rate_events if t >= window_start]
            if len(recent) >= self.rate.count:
                return f"rate limit exceeded: {self.rate.count}/{self.rate.per}"
        if self.max_actions is not None and self._state.action_count + 1 > self.max_actions:
            return f"action count cap exceeded: {self.max_actions}"
        if (
            self.max_spend is not None
            and action.spend is not None
            and self._state.spent + action.spend > self.max_spend
        ):
            return f"spend cap exceeded: {self.max_spend}"
        return None

    # ---- the main entrypoint ----------------------------------------------

    def check(self, action: Action) -> None:
        """Check `action` against all configured limits.

        Raises TripwireTripped (after writing a snapshot to disk) if any
        limit would be violated. Otherwise records the action against the
        persisted counters and returns normally.
        """
        now = time.time()
        reason = self._reason_for_trip(action, now)
        if reason is not None:
            snapshot = self.store.write_pending(action, reason)
            self._notify(snapshot.token, reason, action)
            self._emit_ledger_event("custom", f"Tripwire tripped: {reason}", action)
            raise TripwireTripped(snapshot.token, reason, action)

        self._record(action, now)

    def record_spend(self, action: Action) -> None:
        """Accrue spend for an action that already happened, without a limit
        check. Used by adapters that only learn the true cost of a request
        after the response comes back (see adapters/_httpx_transport.py's
        docstring on why the check and the charge happen at different times).
        """
        self._record(action, time.time())

    def _record(self, action: Action, now: float) -> None:
        if self.rate is not None:
            window_start = self.rate.window_start(now)
            self._state.rate_events = [t for t in self._state.rate_events if t >= window_start]
            self._state.rate_events.append(now)
        self._state.action_count += 1
        if action.spend is not None:
            self._state.spent += action.spend
        self.store.save_state(self._state)

    # ---- resume -------------------------------------------------------

    def resume(self, token: str) -> Decision:
        """Consume the decision for a tripped action, exactly once.

        If approved, the action is recorded against the counters (as if
        `check()` had passed) — approving an over-cap action still counts
        against the cap, it just doesn't trip again for *this* action.
        Callers are responsible for actually performing the action;
        killcord only decides whether it's permitted.
        """
        decision = self.store.resume(token)
        if decision.approved:
            self._record(decision.action, time.time())
        self._emit_ledger_event(
            "custom",
            f"Tripwire resume: {'approved' if decision.approved else 'denied'}",
            decision.action,
        )
        return decision

    # ---- notify / ledger -----------------------------------------------

    def _notify(self, token: str, reason: str, action: Action) -> None:
        if not self.notify_target:
            return
        from killcord.notify.ntfy import send_ntfy_notification

        message = (
            f"{reason}\naction: {action.tool} -> {action.target}\nresume: killcord resume {token}"
        )
        send_ntfy_notification(self.notify_target, title="killcord tripped", message=message)

    def _emit_ledger_event(self, action_type: str, verb: str, action: Action) -> None:
        if self.ledger is None:
            return
        self.ledger.emit(action_type=action_type, verb=verb, target=action.target)


def guarded(tripwire: Tripwire) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator marking a function as running under a Tripwire.

    This does not itself intercept every call the function makes — call
    `tripwire.check(...)` at each point that should be guarded. The
    decorator's job is just to make `TripwireTripped` easy to spot in
    stack traces and to document, at the call site, which tripwire governs
    this loop.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            return func(*args, **kwargs)

        wrapper.__killcord_tripwire__ = tripwire  # type: ignore[attr-defined]
        return wrapper

    return decorator
