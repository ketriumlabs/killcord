from __future__ import annotations

import sys
from types import SimpleNamespace

from typer.testing import CliRunner

from killcord.cli import app


def test_serve_warns_when_binding_to_non_loopback(monkeypatch, tmp_path) -> None:
    import killcord.server.app

    monkeypatch.setattr(killcord.server.app, "create_app", lambda store: object())
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=lambda *args, **kwargs: None))

    result = CliRunner().invoke(app, ["serve", "--host", "0.0.0.0", "--store", str(tmp_path)])

    assert result.exit_code == 0
    assert "no built-in authentication" in result.output


def test_serve_does_not_warn_for_loopback(monkeypatch, tmp_path) -> None:
    import killcord.server.app

    monkeypatch.setattr(killcord.server.app, "create_app", lambda store: object())
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=lambda *args, **kwargs: None))

    result = CliRunner().invoke(app, ["serve", "--host", "127.0.0.1", "--store", str(tmp_path)])

    assert result.exit_code == 0
    assert "WARNING" not in result.output
