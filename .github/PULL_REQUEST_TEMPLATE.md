## What this does

<!-- one or two sentences -->

## Checklist

- [ ] Tests added/updated
- [ ] `ruff check . && ruff format --check .` passes
- [ ] `mypy src/killcord` passes
- [ ] `CHANGELOG.md` updated under `[Unreleased]`
- [ ] If this touches the trip/resume path: crash-injection tests still pass
- [ ] If this changes the public API (`Tripwire`, `guarded`, `Action`, `Rate`,
      `TripwireTripped`): a deprecation path is included, not a hard break
