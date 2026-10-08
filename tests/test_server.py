from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from killcord.core.action import Action
from killcord.server.app import create_app
from killcord.snapshot.store import SnapshotStore


@pytest.fixture
def client(store_dir: Path) -> TestClient:
    return TestClient(create_app(store_dir))


def test_status_page_idle(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Nothing tripped" in resp.text


def test_status_page_shows_pending(client: TestClient, store_dir: Path) -> None:
    store = SnapshotStore(store_dir)
    store.write_pending(Action(tool="buy", target="shop.com", spend=Decimal("10")), "cap exceeded")

    resp = client.get("/")
    assert "TRIPPED" in resp.text
    assert "cap exceeded" in resp.text
    assert "shop.com" in resp.text


def test_decide_approve_via_http(client: TestClient, store_dir: Path) -> None:
    store = SnapshotStore(store_dir)
    snapshot = store.write_pending(Action(tool="buy"), "cap exceeded")

    resp = client.post(f"/decide/{snapshot.token}/approve", follow_redirects=False)
    assert resp.status_code == 303

    pending = store.read_pending()
    assert pending is not None
    assert pending.decision == "approved"


def test_decide_opposite_verdict_returns_conflict(client: TestClient, store_dir: Path) -> None:
    store = SnapshotStore(store_dir)
    snapshot = store.write_pending(Action(tool="buy"), "cap exceeded")
    store.decide(snapshot.token, approved=True)

    resp = client.post(f"/decide/{snapshot.token}/deny", follow_redirects=False)

    assert resp.status_code == 409
    assert resp.json() == {
        "error": "decision_conflict",
        "detail": (
            f"snapshot {snapshot.token!r} already has decision 'approved'; it cannot be changed"
        ),
    }
    pending = store.read_pending()
    assert pending is not None
    assert pending.decision == "approved"


def test_api_status_json(client: TestClient, store_dir: Path) -> None:
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pending"] is None
    assert body["action_count"] == 0


def test_healthz(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.json() == {"status": "ok"}
