from __future__ import annotations

import subprocess
import sys
from pathlib import Path

EXAMPLE = Path(__file__).parent.parent / "examples" / "horror_story.py"


def test_horror_story_demo_end_to_end() -> None:
    result = subprocess.run(
        [sys.executable, str(EXAMPLE), "--auto-approve-first-only"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "exactly one purchase should have gone through" not in result.stdout
    assert "1 purchase(s), not five" in result.stdout
