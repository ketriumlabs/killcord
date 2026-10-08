"""Optional sink that forwards trip/resume events to agent-activity-ledger
as agent-event.v0 records. See ../../../agent-activity-ledger/schema/agent-event.v0.json
— this module's payload shape is pinned to that schema and covered by a
contract test against a local copy of it.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class LedgerSink:
    url: str
    api_key: str
    agent_name: str = "killcord"
    timeout: float = 2.0

    def emit(
        self,
        *,
        action_type: str,
        verb: str,
        trip_id: str,
        event_key: str,
        event_at: float,
    ) -> None:
        try:
            import httpx
        except ImportError:
            return

        payload = {
            "ts": datetime.fromtimestamp(event_at, timezone.utc).isoformat(),
            "actor": {"agent": self.agent_name},
            "action": {"type": action_type, "verb": verb},
            "source": {"integration": "killcord", "version": "0.1.0"},
            "metadata": {"killcord_trip_id": trip_id},
        }

        try:
            response = httpx.post(
                f"{self.url.rstrip('/')}/v1/events",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Idempotency-Key": event_key,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            with contextlib.suppress(Exception):
                logger.warning(
                    "Ledger event delivery failed: HTTP status %s", exc.response.status_code
                )
        except httpx.HTTPError as exc:
            with contextlib.suppress(Exception):
                logger.warning("Ledger event delivery failed: %s", type(exc).__name__)
