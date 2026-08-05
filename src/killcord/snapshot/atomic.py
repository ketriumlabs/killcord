"""Atomic file writes: write-temp + fsync + rename.

A process killed mid-write leaves either the old file intact or the new
file complete — never a torn/partial file. This is the primitive every
crash-safety guarantee in killcord is built on.
"""

from __future__ import annotations

import os
from pathlib import Path


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)  # atomic on POSIX and Windows


def atomic_rename(src: Path, dst: Path) -> None:
    """Atomic rename used to mark a pending snapshot as consumed."""
    os.replace(src, dst)
