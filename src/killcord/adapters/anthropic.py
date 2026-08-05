"""Guard an Anthropic SDK client by intercepting at the httpx transport layer.

    from anthropic import Anthropic
    from killcord.adapters.anthropic import guard_anthropic_client

    client = guard_anthropic_client(Anthropic(), tripwire)

See adapters/openai.py — same approach, same limitations (spend is charged
after the response, using the API's own token usage; pricing table drifts).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx

from killcord.adapters._httpx_transport import GuardedAsyncTransport, GuardedTransport
from killcord.core.tripwire import Tripwire

# Rough per-1K-token USD input+output blended prices. Will drift — see README.
_PRICE_PER_1K_TOKENS_USD = {
    "claude-opus": Decimal("0.03"),
    "claude-sonnet": Decimal("0.006"),
    "claude-haiku": Decimal("0.0015"),
}
_DEFAULT_PRICE_PER_1K = Decimal("0.005")


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

    total_tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    if total_tokens == 0:
        return None

    model = body.get("model", "")
    price = next(
        (p for name, p in _PRICE_PER_1K_TOKENS_USD.items() if name in model),
        _DEFAULT_PRICE_PER_1K,
    )
    return (Decimal(total_tokens) / Decimal(1000)) * price


def guard_anthropic_client(client: Any, tripwire: Tripwire) -> Any:
    """Mutates and returns `client` with its httpx transport wrapped by a
    Tripwire check. Works with both sync (Anthropic) and async
    (AsyncAnthropic) clients."""
    inner_client = client._client
    if isinstance(inner_client, httpx.AsyncClient):
        inner_client._transport = GuardedAsyncTransport(
            tripwire=tripwire,
            wrapped=inner_client._transport,
            tool_name="anthropic",
            spend_estimator=_estimate_spend,
        )
    else:
        inner_client._transport = GuardedTransport(
            tripwire=tripwire,
            wrapped=inner_client._transport,
            tool_name="anthropic",
            spend_estimator=_estimate_spend,
        )
    return client
