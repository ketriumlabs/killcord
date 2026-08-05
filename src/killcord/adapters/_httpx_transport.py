"""Shared machinery for the OpenAI/Anthropic adapters: both SDKs are built on
httpx, so intercepting at the transport layer works regardless of which
higher-level framework is driving the SDK. This is what "framework-agnostic"
actually means in practice — see plan.md's honesty note about that claim.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import httpx

from killcord.core.action import Action
from killcord.core.tripwire import Tripwire

SpendEstimator = Callable[[httpx.Response], Decimal | None]


class GuardedTransport(httpx.BaseTransport):
    """Wraps a real httpx transport; checks a Tripwire before every request
    and estimates spend from the response afterward via `spend_estimator`.

    Spend is charged *after* the response, since it depends on token usage
    reported by the API — but the Tripwire is still checked *before* the
    request goes out, using the account's already-accrued spend. A single
    request can therefore push spend over the cap (its own cost isn't known
    yet); the next request is what actually trips. Document this precisely —
    it's a real, understood limitation, not a bug.
    """

    def __init__(
        self,
        tripwire: Tripwire,
        wrapped: httpx.BaseTransport,
        tool_name: str,
        spend_estimator: SpendEstimator | None = None,
    ) -> None:
        self._tripwire = tripwire
        self._wrapped = wrapped
        self._tool_name = tool_name
        self._spend_estimator = spend_estimator

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self._tripwire.check(Action(tool=self._tool_name, target=str(request.url)))
        response = self._wrapped.handle_request(request)
        if self._spend_estimator is not None:
            response.read()  # buffer body so the estimator can inspect it safely
            estimated = self._spend_estimator(response)
            if estimated is not None:
                self._tripwire.record_spend(
                    Action(tool=self._tool_name, target=str(request.url), spend=estimated)
                )
        return response


class GuardedAsyncTransport(httpx.AsyncBaseTransport):
    """Async counterpart of GuardedTransport, for AsyncOpenAI/AsyncAnthropic clients."""

    def __init__(
        self,
        tripwire: Tripwire,
        wrapped: httpx.AsyncBaseTransport,
        tool_name: str,
        spend_estimator: SpendEstimator | None = None,
    ) -> None:
        self._tripwire = tripwire
        self._wrapped = wrapped
        self._tool_name = tool_name
        self._spend_estimator = spend_estimator

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self._tripwire.check(Action(tool=self._tool_name, target=str(request.url)))
        response = await self._wrapped.handle_async_request(request)
        if self._spend_estimator is not None:
            await response.aread()
            estimated = self._spend_estimator(response)
            if estimated is not None:
                self._tripwire.record_spend(
                    Action(tool=self._tool_name, target=str(request.url), spend=estimated)
                )
        return response
