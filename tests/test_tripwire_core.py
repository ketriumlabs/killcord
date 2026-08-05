from __future__ import annotations

import contextlib
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from killcord.core.action import Action
from killcord.core.rate import Rate
from killcord.core.tripwire import Tripwire, TripwireTripped


def make_tripwire(store_dir: Path, **kwargs: object) -> Tripwire:
    return Tripwire(store=store_dir, **kwargs)  # type: ignore[arg-type]


def test_no_limits_never_trips(store_dir: Path) -> None:
    tw = make_tripwire(store_dir)
    for i in range(100):
        tw.check(Action(tool="anything", target=f"x{i}.com"))


def test_max_actions_trips_exactly_at_cap(store_dir: Path) -> None:
    tw = make_tripwire(store_dir, max_actions=3)
    for _ in range(3):
        tw.check(Action(tool="x"))
    with pytest.raises(TripwireTripped):
        tw.check(Action(tool="x"))


@given(st.integers(min_value=0, max_value=50))
@settings(max_examples=20)
def test_action_count_never_exceeds_cap(tmp_path_factory, cap: int) -> None:
    store_dir = tmp_path_factory.mktemp("kc")
    tw = make_tripwire(store_dir, max_actions=cap)
    allowed = 0
    for _ in range(cap + 10):
        try:
            tw.check(Action(tool="x"))
            allowed += 1
        except TripwireTripped:
            break
    assert allowed == cap
    assert tw.store.load_state().action_count == cap


def test_max_spend_trips_when_action_would_exceed(store_dir: Path) -> None:
    tw = make_tripwire(store_dir, max_spend=Decimal("100"))
    tw.check(Action(tool="buy", spend=Decimal("60")))
    with pytest.raises(TripwireTripped, match="spend cap"):
        tw.check(Action(tool="buy", spend=Decimal("50")))


@given(
    spends=st.lists(
        st.decimals(min_value="0.01", max_value="20", places=2), min_size=1, max_size=30
    ),
    cap=st.decimals(min_value="1", max_value="100", places=2),
)
@settings(max_examples=20)
def test_spend_never_exceeds_cap(tmp_path_factory, spends: list[Decimal], cap: Decimal) -> None:
    store_dir = tmp_path_factory.mktemp("kc")
    tw = make_tripwire(store_dir, max_spend=cap)
    for spend in spends:
        with contextlib.suppress(TripwireTripped):
            tw.check(Action(tool="buy", spend=spend))
    assert tw.store.load_state().spent <= cap


def test_rate_limit_trips_within_window(store_dir: Path) -> None:
    tw = make_tripwire(store_dir, rate=Rate(count=3, per="minute"))
    for _ in range(3):
        tw.check(Action(tool="x"))
    with pytest.raises(TripwireTripped, match="rate limit"):
        tw.check(Action(tool="x"))


def test_allow_tools_blocks_unlisted_tool(store_dir: Path) -> None:
    tw = make_tripwire(store_dir, allow_tools=["search"])
    tw.check(Action(tool="search"))
    with pytest.raises(TripwireTripped, match="allowlist"):
        tw.check(Action(tool="purchase"))


def test_allow_domains_blocks_unlisted_domain(store_dir: Path) -> None:
    tw = make_tripwire(store_dir, allow_domains=["*.mycompany.com"])
    tw.check(Action(tool="x", target="https://api.mycompany.com/foo"))
    with pytest.raises(TripwireTripped, match="not in the allowed domains"):
        tw.check(Action(tool="x", target="https://evil.com"))


def test_allow_domains_exact_match(store_dir: Path) -> None:
    tw = make_tripwire(store_dir, allow_domains=["mycompany.com"])
    tw.check(Action(tool="x", target="mycompany.com"))


def test_state_persists_across_tripwire_instances(store_dir: Path) -> None:
    tw1 = make_tripwire(store_dir, max_actions=5)
    for _ in range(3):
        tw1.check(Action(tool="x"))

    # A fresh Tripwire pointed at the same store must see the persisted count —
    # counters surviving a restart is what stops caps being reset by crashing.
    tw2 = make_tripwire(store_dir, max_actions=5)
    for _ in range(2):
        tw2.check(Action(tool="x"))
    with pytest.raises(TripwireTripped):
        tw2.check(Action(tool="x"))


def test_trip_writes_a_pending_snapshot(store_dir: Path) -> None:
    tw = make_tripwire(store_dir, max_actions=0)
    with pytest.raises(TripwireTripped) as exc_info:
        tw.check(Action(tool="buy", target="shop.com", spend=Decimal("10")))

    pending = tw.store.read_pending()
    assert pending is not None
    assert pending.token == exc_info.value.snapshot_id
    assert pending.action.tool == "buy"


def test_resume_approved_records_the_action(store_dir: Path) -> None:
    tw = make_tripwire(store_dir, max_actions=0)
    with pytest.raises(TripwireTripped) as exc_info:
        tw.check(Action(tool="buy", spend=Decimal("10")))
    token = exc_info.value.snapshot_id

    tw.store.decide(token, approved=True)
    decision = tw.resume(token)

    assert decision.approved
    assert tw.store.load_state().action_count == 1


def test_resume_denied_does_not_record(store_dir: Path) -> None:
    tw = make_tripwire(store_dir, max_actions=0)
    with pytest.raises(TripwireTripped) as exc_info:
        tw.check(Action(tool="buy"))
    token = exc_info.value.snapshot_id

    tw.store.decide(token, approved=False)
    decision = tw.resume(token)

    assert not decision.approved
    assert tw.store.load_state().action_count == 0


def test_resume_twice_raises_already_consumed(store_dir: Path) -> None:
    from killcord.snapshot.store import AlreadyConsumedError

    tw = make_tripwire(store_dir, max_actions=0)
    with pytest.raises(TripwireTripped) as exc_info:
        tw.check(Action(tool="buy"))
    token = exc_info.value.snapshot_id

    tw.store.decide(token, approved=True)
    tw.resume(token)

    with pytest.raises(AlreadyConsumedError):
        tw.resume(token)


def test_context_manager_usage(store_dir: Path) -> None:
    with make_tripwire(store_dir, max_actions=5) as tw:
        tw.check(Action(tool="x"))
    assert tw.store.load_state().action_count == 1
