# Contributing to killcord

## Dev setup (5 commands)

```bash
git clone https://github.com/ketriumlabs/killcord.git
cd killcord
uv venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
uv pip install -e ".[dev]"
pytest
```

## Before you open a PR

- `ruff check . && ruff format --check .`
- `mypy src/killcord`
- `pytest --cov` — the `core/` and `snapshot/` packages should stay above 85% coverage
- If you touched anything in `snapshot/` or the trip/resume path, run the crash-injection
  tests specifically: `pytest tests/test_crash_injection.py -v`. These are the tests that
  matter most — see [docs/resume-semantics.md](docs/resume-semantics.md) for why.
- Update `CHANGELOG.md` under `[Unreleased]`

## API stability

killcord is a library. Its public API (`Tripwire`, `guarded`, `Action`, `Rate`,
`TripwireTripped`) is the product. Breaking changes to that surface require a
deprecation warning one minor version before removal, even pre-1.0 — see
[plan.md](plan.md#versioning--releases).

## Commit style

[Conventional Commits](https://www.conventionalcommits.org/). PRs are squash-merged.

## Adding an adapter

New framework adapters live under `src/killcord/adapters/`. They must:
1. Call `tripwire.check(...)` before the framework's real network/tool call happens.
2. Ship a test that runs `examples/horror_story.py`'s scenario through the adapter.
3. Come with a short README section under `docs/adapters/`.
