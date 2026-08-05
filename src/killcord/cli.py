from __future__ import annotations

import typer

app = typer.Typer(help="killcord — spending caps, rate limits, and a big red pause button.")

DEFAULT_STORE = "~/.killcord/default"


@app.command()
def serve(
    store: str = typer.Option(DEFAULT_STORE, help="Path to the Tripwire's snapshot store"),
    host: str = typer.Option("127.0.0.1", help="Bind address"),
    port: int = typer.Option(8710, help="Bind port"),
) -> None:
    """Start the pause server: the big red button + live status."""
    import uvicorn

    from killcord.server.app import create_app

    app_instance = create_app(store)
    uvicorn.run(app_instance, host=host, port=port)


@app.command()
def status(store: str = typer.Option(DEFAULT_STORE)) -> None:
    """Print the current tripwire state and any pending decision."""
    from killcord.snapshot.store import SnapshotStore

    s = SnapshotStore(store)
    state = s.load_state()
    typer.echo(f"spent={state.spent} action_count={state.action_count}")
    pending = s.read_pending()
    if pending is None:
        typer.echo("nothing pending")
    else:
        typer.echo(
            f"PENDING token={pending.token} reason={pending.reason!r} "
            f"decision={pending.decision or '(none yet)'}"
        )


@app.command()
def approve(token: str, store: str = typer.Option(DEFAULT_STORE)) -> None:
    """Approve a tripped action so the loop can resume."""
    from killcord.snapshot.store import SnapshotStore

    SnapshotStore(store).decide(token, approved=True)
    typer.echo(f"approved {token}")


@app.command()
def deny(token: str, store: str = typer.Option(DEFAULT_STORE)) -> None:
    """Deny a tripped action."""
    from killcord.snapshot.store import SnapshotStore

    SnapshotStore(store).decide(token, approved=False)
    typer.echo(f"denied {token}")


@app.command()
def resume(token: str, store: str = typer.Option(DEFAULT_STORE)) -> None:
    """Consume the decision for a tripped action (exactly once) and print it.

    This talks to the snapshot store directly, not to a live Tripwire — it
    consumes the pending decision but does NOT accrue spend/action counters
    (a Tripwire object does that in-process). Use this for inspection or
    scripting; the normal flow is your agent loop calling
    `tripwire.resume(token)` itself so counters stay accurate.
    """
    from killcord.snapshot.store import AlreadyConsumedError, NoPendingSnapshotError, SnapshotStore

    try:
        decision = SnapshotStore(store).resume(token)
    except NoPendingSnapshotError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except AlreadyConsumedError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        f"approved={decision.approved} action={decision.action.tool} -> {decision.action.target}"
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
