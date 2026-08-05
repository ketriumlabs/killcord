"""Guard an OpenAI SDK client by intercepting at the httpx transport layer.

    from openai import OpenAI
    from killcord.adapters.openai import guard_openai_client

    client = guard_openai_client(OpenAI(), tripwire)

Every request the client makes is checked against `tripwire` before it goes
out; spend is estimated from the `usage` field in chat/completions responses
and accrued afterward. Works with any code that calls this client, regardless
of what agent framework is driving it — that's the point of intercepting at
the transport layer instead of wrapping the SDK's Python methods.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx

from killcord.adapters._httpx_transport import GuardedAsyncTransport, GuardedTransport
from killcord.core.tripwire import Tripwire

# Rough per-1K-token USD prices for spend estimation. This table WILL drift —
# treat max_spend as a strong signal, not exact accounting. See README.
_PRICE_PER_1K_TOKENS_USD = {
    "gpt-4o": Decimal("0.005"),
    "gpt-4o-mini": Decimal("0.00015"),
    "gpt-4-turbo": Decimal("0.01"),
    "gpt-3.5-turbo": Decimal("0.0005"),
}
_DEFAULT_PRICE_PER_1K = Decimal("0.002")


def _estimate_spend(response: httpx.Response) -> Decimal | None:
    if response.status_code >= 400:
        return None
    try:
        body: dict[str, Any] = json.loads(response.content)
    except (ValueError, UnicodeDecodeError):
        return None

    usage = body.get("usage")
    if not usage:
        return None

    total_tokens = usage.get("total_tokens")
    if total_tokens is None:
        return None

    model = body.get("model", "")
    price = next(
        (p for name, p in _PRICE_PER_1K_TOKENS_USD.items() if model.startswith(name)),
        _DEFAULT_PRICE_PER_1K,
    )
    return (Decimal(total_tokens) / Decimal(1000)) * price


def guard_openai_client(client: Any, tripwire: Tripwire) -> Any:
    """Mutates and returns `client` with its httpx transport wrapped by a
    Tripwire check. Works with both sync (OpenAI) and async (AsyncOpenAI)
    clients — detected from the underlying httpx client type."""
    inner_client = client._client  # the underlying httpx.Client/AsyncClient
    if isinstance(inner_client, httpx.AsyncClient):
        inner_client._transport = GuardedAsyncTransport(
            tripwire=tripwire,
            wrapped=inner_client._transport,
            tool_name="openai",
            spend_estimator=_estimate_spend,
        )
    else:
        inner_client._transport = GuardedTransport(
            tripwire=tripwire,
            wrapped=inner_client._transport,
            tool_name="openai",
            spend_estimator=_estimate_spend,
        )
    return client
