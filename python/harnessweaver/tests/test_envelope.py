from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from harnessweaver import Budget, Envelope, FakeClock, Labels, Principal, SystemClock


def test_envelope_new_sets_ids_and_deadline_from_budget() -> None:
    clock = FakeClock()
    env = Envelope.new(
        tenant="acme", principal="alice", budget=Budget(deadline=timedelta(minutes=5)), clock=clock
    )
    assert env.run_id.startswith("run_")
    assert env.principal == Principal(id="alice")
    assert env.deadline == clock.now() + timedelta(minutes=5)
    assert env.clock is clock


def test_envelope_is_immutable() -> None:
    env = Envelope.new(tenant="acme", principal="alice")
    with pytest.raises(ValidationError):
        env.tenant = "other"  # type: ignore[misc]


def test_envelope_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Envelope(run_id="r", tenant="t", principal="p", surprise=1)  # type: ignore[call-arg]


def test_remaining_time_follows_the_clock() -> None:
    clock = FakeClock()
    env = Envelope.new(
        tenant="t", principal="p", budget=Budget(deadline=timedelta(minutes=1)), clock=clock
    )
    clock.advance("45s")
    assert env.remaining() == timedelta(seconds=15)
    clock.advance("1h")
    assert env.remaining() == timedelta(0)
    assert Envelope.new(tenant="t", principal="p").remaining() is None


def test_copies_keep_the_clock() -> None:
    clock = FakeClock()
    env = Envelope.new(tenant="t", principal="p", clock=clock)
    labelled = env.with_labels(env.labels.mark_untrusted("kb"))
    assert labelled.clock is clock
    assert labelled.labels.untrusted_seen
    other = FakeClock()
    assert env.with_clock(other).clock is other


def test_envelope_round_trips_through_json_without_the_clock() -> None:
    env = Envelope.new(
        tenant="t", principal="p", budget=Budget(max_usd=1.5, deadline=timedelta(seconds=20))
    )
    data = env.model_dump(mode="json")
    assert data["budget"]["deadline"] == "20s"
    assert "clock" not in data
    assert "_clock" not in data
    restored = Envelope.model_validate(data)
    assert restored == env
    assert isinstance(restored.clock, SystemClock)


def test_labels_record_sources_once_in_order() -> None:
    labels = Labels().mark_untrusted("kb").mark_private("crm").mark_untrusted("kb")
    assert labels.untrusted_seen
    assert labels.private_seen
    assert labels.sources == ("kb", "crm")


def test_budget_intersection_takes_the_tightest_limits() -> None:
    a = Budget.model_validate({"max_usd": 2.0, "max_tool_calls": 20, "deadline": "5m"})
    b = Budget.model_validate({"max_usd": 0.5, "max_tokens": 1000, "deadline": "20s"})
    assert a.intersect(b) == Budget(
        max_usd=0.5, max_tokens=1000, max_tool_calls=20, deadline=timedelta(seconds=20)
    )


def test_budget_rejects_negative_limits() -> None:
    with pytest.raises(ValidationError):
        Budget(max_usd=-1)
    with pytest.raises(ValidationError):
        Budget.model_validate({"deadline": "-5s"})


def test_fake_clock_moves_only_when_told() -> None:
    clock = FakeClock(datetime(2026, 1, 10, 12, 0, tzinfo=UTC))  # a Saturday
    assert clock.is_weekend()
    clock.advance(timedelta(days=2))
    assert not clock.is_weekend()
    clock.set(datetime(2026, 3, 1, tzinfo=UTC))
    assert clock.now() == datetime(2026, 3, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="timezone-aware"):
        FakeClock(datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="timezone-aware"):
        clock.set(datetime(2026, 1, 1))


def test_system_clock_is_timezone_aware() -> None:
    assert SystemClock().now().tzinfo is not None
