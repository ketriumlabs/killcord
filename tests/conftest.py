from __future__ import annotations

from pathlib import Path

import pytest

from killcord.snapshot.store import SnapshotStore


@pytest.fixture
def store_dir(tmp_path: Path) -> Path:
    return tmp_path / "killcord-store"


@pytest.fixture
def store(store_dir: Path) -> SnapshotStore:
    return SnapshotStore(store_dir)
