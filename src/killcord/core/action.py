"""The unit killcord checks: a pending action an agent is about to take."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class Action:
    """A pending action, checked against a Tripwire before it's allowed to proceed.

    `tool` and `target` are free-form strings the caller controls — killcord
    doesn't know what "browser.purchase" or "amazon.com" mean, it just checks
    them against the configured allowlists.
    """

    tool: str
    target: str | None = None
    spend: Decimal | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def domain(self) -> str | None:
        """Best-effort domain extraction from `target`, for allow_domains checks."""
        if self.target is None:
            return None
        if "://" in self.target:
            parsed = urlparse(self.target)
            return parsed.netloc or None
        # bare "amazon.com" / "sub.amazon.com" form
        if "/" not in self.target and "." in self.target:
            return self.target
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "target": self.target,
            "spend": str(self.spend) if self.spend is not None else None,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Action:
        return Action(
            tool=d["tool"],
            target=d.get("target"),
            spend=Decimal(d["spend"]) if d.get("spend") is not None else None,
            metadata=d.get("metadata", {}),
        )
