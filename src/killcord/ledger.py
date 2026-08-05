"""Optional sink that forwards trip/resume events to agent-activity-ledger
as agent-event.v0 records. See ../../../agent-activity-ledger/schema/agent-event.v0.json
— this module's payload shape is pinned to that schema and covered by a
contract test against a local copy of it.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class LedgerSink:
    url: str
    api_key: str
    agent_name: str = "killcord"
    timeout: float = 5.0

    def emit(self, *, action_type: str, verb: str, target: str | None = None) -> None:
        try:
            import httpx
        except ImportError:
            return

        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),  # py3.10 floor: no datetime.UTC alias
            "actor": {"agent": self.agent_name},
            "action": {"type": action_type, "verb": verb},
            "source": {"integration": "killcord", "version": "0.1.0"},
        }
        if target:
            payload["target"] = target

        with contextlib.suppress(httpx.HTTPError):  # logging must never break the caller's loop
            httpx.post(
                f"{self.url.rstrip('/')}/v1/events",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
