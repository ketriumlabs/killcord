"""ntfy.sh push notification backend — free push to a phone, no account needed.

`notify="ntfy://my-topic-name"` sends a plain HTTP POST to
https://ntfy.sh/my-topic-name. Anyone who knows the topic name can read it,
so pick something unguessable (killcord doesn't generate one for you — that's
a deliberate choice to avoid a false sense of secrecy around a public service).
"""

from __future__ import annotations


def _parse_target(target: str) -> tuple[str, str]:
    """'ntfy://topic' -> (server, topic); 'ntfy://myserver.example.com/topic' -> custom server."""
    if not target.startswith("ntfy://"):
        raise ValueError(f"unsupported notify target: {target!r} (expected ntfy://...)")
    rest = target[len("ntfy://") :]
    if "/" in rest:
        server, topic = rest.split("/", 1)
        return f"https://{server}", topic
    return "https://ntfy.sh", rest


def send_ntfy_notification(target: str, title: str, message: str) -> bool:
    """Best-effort push. Returns False (never raises) on any failure — a
    notification failure must never crash the caller's agent loop."""
    try:
        import httpx
    except ImportError:
        return False

    server, topic = _parse_target(target)
    try:
        resp = httpx.post(
            f"{server}/{topic}",
            content=message.encode("utf-8"),
            headers={"Title": title, "Priority": "high", "Tags": "rotating_light"},
            timeout=5.0,
        )
        return resp.status_code < 300
    except httpx.HTTPError:
        return False
