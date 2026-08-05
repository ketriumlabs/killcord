"""LangChain/LangGraph callback: checks a Tripwire before every tool call.

    from killcord.adapters.langchain import KillcordCallbackHandler

    handler = KillcordCallbackHandler(tripwire)
    agent_executor.invoke({"input": "..."}, config={"callbacks": [handler]})

Raising TripwireTripped from a callback propagates out of `.invoke()` —
LangChain doesn't swallow callback exceptions by design, so this actually
stops the run.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from killcord.core.action import Action
from killcord.core.tripwire import Tripwire

# Tool-name substrings that hint at a spend-relevant action needing a
# non-None Action.spend so max_spend actually engages. Everything else is
# checked against max_actions/rate/allowlists only. Callers can subclass
# and override `estimate_spend` for exact accounting.
_SPEND_HINTS = ("purchase", "buy", "checkout", "book", "pay")


class KillcordCallbackHandler(BaseCallbackHandler):
    def __init__(self, tripwire: Tripwire) -> None:
        self.tripwire = tripwire

    def estimate_spend(self, tool_name: str, input_str: str) -> Decimal | None:
        """Override this for real spend accounting — the default is a dumb
        heuristic that assigns no spend at all, so max_spend won't trip
        unless you provide better estimation."""
        return None

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        tool_name = serialized.get("name", "unknown_tool")
        action = Action(
            tool=tool_name,
            target=input_str[:500],
            spend=self.estimate_spend(tool_name, input_str),
        )
        self.tripwire.check(action)  # raises TripwireTripped, which LangChain propagates
