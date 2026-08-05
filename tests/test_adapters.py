from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from killcord.adapters._httpx_transport import GuardedTransport
from killcord.adapters.openai import _estimate_spend as openai_estimate_spend
from killcord.adapters.openai import guard_openai_client
from killcord.core.tripwire import Tripwire, TripwireTripped


def _fake_openai_transport(
    total_tokens: int = 100, model: str = "gpt-4o-mini"
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"model": model, "usage": {"total_tokens": total_tokens}, "choices": []},
        )

    return httpx.MockTransport(handler)


def test_guarded_transport_checks_before_request(store_dir: Path) -> None:
    tw = Tripwire(allow_tools=["search"], store=store_dir)
    transport = GuardedTransport(tw, _fake_openai_transport(), tool_name="purchase")
    client = httpx.Client(transport=transport)

    with pytest.raises(TripwireTripped):
        client.get("https://api.example.com/v1/thing")


def test_guarded_transport_accrues_spend_from_response(store_dir: Path) -> None:
    tw = Tripwire(max_spend=Decimal("100"), store=store_dir)
    transport = GuardedTransport(
        tw,
        _fake_openai_transport(total_tokens=1000, model="gpt-4o"),
        tool_name="openai",
        spend_estimator=openai_estimate_spend,
    )
    client = httpx.Client(transport=transport)

    resp = client.post("https://api.openai.com/v1/chat/completions", json={})
    assert resp.status_code == 200
    # 1000 tokens at gpt-4o's $0.005/1K = $0.005
    assert tw.store.load_state().spent == Decimal("0.005")


def test_guarded_openai_client_wraps_transport(store_dir: Path) -> None:
    class FakeInnerClient:
        def __init__(self) -> None:
            self._transport = _fake_openai_transport()

    class FakeOpenAI:
        def __init__(self) -> None:
            self._client = FakeInnerClient()

    tw = Tripwire(max_actions=1, store=store_dir)
    client = guard_openai_client(FakeOpenAI(), tw)
    assert isinstance(client._client._transport, GuardedTransport)


def test_openai_estimate_spend_unknown_model_falls_back_to_default() -> None:
    response = httpx.Response(
        200, json={"model": "some-future-model", "usage": {"total_tokens": 1000}}
    )
    spend = openai_estimate_spend(response)
    assert spend == Decimal("0.002")  # _DEFAULT_PRICE_PER_1K


def test_openai_estimate_spend_no_usage_returns_none() -> None:
    response = httpx.Response(200, json={"model": "gpt-4o"})
    assert openai_estimate_spend(response) is None


def test_openai_estimate_spend_error_response_returns_none() -> None:
    response = httpx.Response(400, json={"error": "bad request"})
    assert openai_estimate_spend(response) is None
