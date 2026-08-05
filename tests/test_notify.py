from __future__ import annotations

import httpx
import pytest

from killcord.notify.ntfy import _parse_target, send_ntfy_notification


def test_parse_target_default_server() -> None:
    assert _parse_target("ntfy://my-topic") == ("https://ntfy.sh", "my-topic")


def test_parse_target_custom_server() -> None:
    assert _parse_target("ntfy://ntfy.example.com/my-topic") == (
        "https://ntfy.example.com",
        "my-topic",
    )


def test_parse_target_rejects_bad_scheme() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        _parse_target("https://ntfy.sh/topic")


def test_send_notification_never_raises_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_error(*args: object, **kwargs: object) -> None:
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(httpx, "post", raise_error)
    result = send_ntfy_notification("ntfy://topic", "title", "message")
    assert result is False


def test_send_notification_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status_code = 200

    monkeypatch.setattr(httpx, "post", lambda *a, **kw: FakeResponse())
    result = send_ntfy_notification("ntfy://topic", "title", "message")
    assert result is True
