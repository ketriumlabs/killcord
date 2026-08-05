"""A simple sliding-window rate limit: N actions per `period` seconds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

_PERIOD_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}

PeriodName = Literal["second", "minute", "hour", "day"]


@dataclass(frozen=True)
class Rate:
    count: int
    per: PeriodName = "minute"

    @property
    def period_seconds(self) -> float:
        return float(_PERIOD_SECONDS[self.per])

    def window_start(self, now: float) -> float:
        return now - self.period_seconds
