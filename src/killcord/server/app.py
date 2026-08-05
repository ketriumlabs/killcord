"""The pause server: a tiny, phone-friendly local page with the big red
button and current status. Shows the exact action that tripped the wire.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from killcord.snapshot.store import NoPendingSnapshotError, SnapshotStore

_templates_dir = resources.files("killcord.server").joinpath("templates")
templates = Jinja2Templates(directory=str(_templates_dir))


def create_app(store_dir: str | Path = "~/.killcord/default") -> FastAPI:
    store = SnapshotStore(Path(store_dir).expanduser())
    app = FastAPI(title="killcord pause server")
    app.state.store = store

    @app.get("/", response_class=HTMLResponse)
    def status(request: Request) -> HTMLResponse:
        pending = store.read_pending()
        state = store.load_state()
        return templates.TemplateResponse(
            request,
            "status.html",
            {"pending": pending, "state": state},
        )

    @app.post("/decide/{token}/{verdict}")
    def decide(token: str, verdict: str) -> RedirectResponse:
        if verdict not in ("approve", "deny"):
            return RedirectResponse("/", status_code=303)
        store.decide(token, approved=(verdict == "approve"))
        return RedirectResponse("/", status_code=303)

    @app.get("/api/status")
    def api_status() -> dict[str, Any]:
        pending = store.read_pending()
        state = store.load_state()
        return {
            "pending": pending.to_dict() if pending else None,
            "spent": str(state.spent),
            "action_count": state.action_count,
        }

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


__all__ = ["create_app", "NoPendingSnapshotError"]
