from __future__ import annotations

import json
from pathlib import Path

import httpx
import jsonschema
import pytest

from killcord.ledger import LedgerSink

SCHEMA_PATH = Path(__file__).parent / "fixtures" / "agent-event.v0.json"


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _validate(instance: dict, schema: dict) -> None:
    validator = jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
    )
    validator.validate(instance)


def test_ledger_sink_emits_schema_valid_payload(
    monkeypatch: pytest.MonkeyPatch, schema: dict
) -> None:
    captured: dict = {}

    def fake_post(url: str, json: dict, headers: dict, timeout: float) -> httpx.Response:
        captured["payload"] = json
        captured["url"] = url
        captured["headers"] = headers
        return httpx.Response(201)

    monkeypatch.setattr(httpx, "post", fake_post)

    sink = LedgerSink(url="http://127.0.0.1:8420", api_key="lgr_test")
    sink.emit(action_type="custom", verb="Tripwire tripped: spend cap exceeded", target="shop.com")

    assert captured["url"] == "http://127.0.0.1:8420/v1/events"
    assert captured["headers"]["Authorization"] == "Bearer lgr_test"
    _validate(captured["payload"], schema)


def test_ledger_sink_never_raises_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_error(*args: object, **kwargs: object) -> None:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "post", raise_error)

    sink = LedgerSink(url="http://127.0.0.1:8420", api_key="lgr_test")
    sink.emit(action_type="custom", verb="x")  # must not raise
