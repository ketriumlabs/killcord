"""Crash-safety tests for the snapshot store.

These are the tests that matter most (see docs/resume-semantics.md): a
process can be killed at any point, and neither the counter state nor the
pending-snapshot file should ever end up torn/partial, and a tripped action
must never be resumable twice.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from killcord.core.action import Action
from killcord.snapshot.atomic import atomic_write_text
from killcord.snapshot.store import (
    AlreadyConsumedError,
    CounterState,
    NoPendingSnapshotError,
    SnapshotStore,
)


def test_atomic_write_never_leaves_a_torn_file(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    atomic_write_text(target, '{"a": 1}')
    assert json.loads(target.read_text()) == {"a": 1}

    # A write that fails partway through (simulated: os.replace never called
    # because the write itself raised) must not have touched the real file.
    with (
        patch("killcord.snapshot.atomic.os.fsync", side_effect=OSError("disk full")),
        pytest.raises(OSError, match="disk full"),
    ):
        atomic_write_text(target, '{"a": 2, "b": "corrupt-if-torn"}')

    # Original file must be untouched — the failed write's tmp file is orphaned,
    # not the real path.
    assert json.loads(target.read_text()) == {"a": 1}


def test_save_state_survives_a_crash_between_writes(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path)
    store.save_state(CounterState(spent=Decimal("5"), action_count=1))

    # Simulate a crash mid-write on the *next* save: os.replace never runs.
    with (
        patch("killcord.snapshot.atomic.os.replace", side_effect=OSError("killed")),
        pytest.raises(OSError),
    ):
        store.save_state(CounterState(action_count=999))

    # A fresh store re-reads the last successfully committed state, not a
    # torn/partial one.
    reloaded = SnapshotStore(tmp_path).load_state()
    assert reloaded.action_count == 1


def test_resume_crash_after_rename_is_not_re_resumable(tmp_path: Path) -> None:
    """Simulates: the rename that consumes the snapshot succeeds, but the
    process is killed before returning the Decision to the caller. The
    at-most-once guarantee must still hold — a second process finding the
    store afterward must see it as already consumed, never as pending."""
    store = SnapshotStore(tmp_path)
    snapshot = store.write_pending(Action(tool="buy"), reason="cap exceeded")
    store.decide(snapshot.token, approved=True)

    from killcord.snapshot import store as store_module

    original_atomic_rename = store_module.atomic_rename

    def crash_after_rename(src: Path, dst: Path) -> None:
        original_atomic_rename(src, dst)
        raise SystemExit("simulated crash right after the rename committed")

    with (
        patch.object(store_module, "atomic_rename", side_effect=crash_after_rename),
        pytest.raises(SystemExit),
    ):
        store.resume(snapshot.token)

    # The rename went through before the "crash" — a second resume attempt,
    # as if a new process restarted and tried again, must see it as consumed.
    with pytest.raises(AlreadyConsumedError):
        store.resume(snapshot.token)


def test_resume_without_decision_raises(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path)
    snapshot = store.write_pending(Action(tool="buy"), reason="cap exceeded")
    with pytest.raises(NoPendingSnapshotError):
        store.resume(snapshot.token)


def test_resume_with_wrong_token_raises(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path)
    store.write_pending(Action(tool="buy"), reason="cap exceeded")
    with pytest.raises(NoPendingSnapshotError):
        store.resume("not-the-real-token")


def test_resume_with_nothing_pending_raises(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path)
    with pytest.raises(NoPendingSnapshotError):
        store.resume("anything")


def test_concurrent_resume_race_only_one_wins(tmp_path: Path) -> None:
    """A second, truly-concurrent resume() call (source file already moved
    by the first, no consumed-marker check reached yet) must still fail
    cleanly rather than double-permit."""
    store = SnapshotStore(tmp_path)
    snapshot = store.write_pending(Action(tool="buy"), reason="cap exceeded")
    store.decide(snapshot.token, approved=True)

    first = store.resume(snapshot.token)
    assert first.approved

    with pytest.raises(AlreadyConsumedError):
        store.resume(snapshot.token)


def test_new_trip_after_previous_consumed_snapshot_works(tmp_path: Path) -> None:
    """A consumed-marker from a previous trip must not block a brand new trip."""
    store = SnapshotStore(tmp_path)
    first = store.write_pending(Action(tool="buy"), reason="first")
    store.decide(first.token, approved=True)
    store.resume(first.token)

    second = store.write_pending(Action(tool="buy"), reason="second")
    store.decide(second.token, approved=True)
    decision = store.resume(second.token)
    assert decision.token == second.token
