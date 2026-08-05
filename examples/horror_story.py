#!/usr/bin/env python
"""The headline demo: an agent told to "buy the cheapest flight" tries to buy
5 (a classic runaway-loop bug — it kept retrying after a fake "still
searching" response instead of stopping once it found one). killcord trips
on the 2nd purchase, a human reviews and approves *that specific one*, and
the loop resumes having bought exactly one flight — not zero, not five.

Run interactively:   python examples/horror_story.py
Run in CI:            python examples/horror_story.py --auto-approve-first-only
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252

from killcord import Action, Tripwire, TripwireTripped  # noqa: E402


def buggy_flight_booking_agent(tripwire: Tripwire, purchases: list[Decimal]) -> None:
    """Simulates a bug: the agent doesn't realize it already booked a flight
    and keeps "finding a cheaper one" 5 times in a row."""
    for i in range(5):
        price = Decimal("199.00") - Decimal(i) * Decimal("5")
        action = Action(tool="browser.purchase", target="airline.example.com", spend=price)
        tripwire.check(action)  # trips immediately — every purchase needs review
        purchases.append(price)
        print(f"  bought flight #{i + 1} for ${price}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--auto-approve-first-only",
        action="store_true",
        help="Non-interactive mode for CI: approve the first trip, then stop.",
    )
    args = parser.parse_args()

    store_dir = tempfile.mkdtemp(prefix="killcord-horror-story-")
    try:
        # max_actions=0: every purchase needs human review before it happens —
        # this is what makes "exactly one, not five" possible. If we allowed
        # one free action before tripping, the buggy loop's first (unreviewed)
        # purchase would already have gone through by the time a human saw it.
        tripwire = Tripwire(max_actions=0, store=store_dir)
        purchases: list[Decimal] = []

        print("Agent: 'find me the cheapest flight' (bug: it keeps re-searching)")
        try:
            buggy_flight_booking_agent(tripwire, purchases)
            print("BUG IN DEMO: should have tripped by now")
            sys.exit(1)
        except TripwireTripped as trip:
            print(f"\n🔴 TRIPPED: {trip.reason}")
            pending_line = (
                f"   pending action: {trip.action.tool} -> "
                f"{trip.action.target} (${trip.action.spend})"
            )
            print(pending_line)
            print(f"   snapshot: {trip.snapshot_id}")

            if args.auto_approve_first_only:
                approved = True
            else:
                answer = input("\n   Approve this purchase? [y/N] ").strip().lower()
                approved = answer == "y"

            tripwire.store.decide(trip.snapshot_id, approved=approved)
            decision = tripwire.resume(trip.snapshot_id)

            if decision.approved:
                purchases.append(decision.action.spend or Decimal("0"))
                print("   ✅ approved — proceeding with 1 purchase, not re-running the buggy loop")
            else:
                print("   🚫 denied — no purchase made")

        print(f"\nFinal result: {len(purchases)} flight(s) purchased: {purchases}")
        expected = 1 if approved else 0
        assert len(purchases) == expected, "purchase count didn't match the approve/deny decision"
        print(f"✅ horror story resolved correctly: {expected} purchase(s), not five.")
    finally:
        shutil.rmtree(store_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
