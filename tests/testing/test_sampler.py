import logging
from unittest.mock import MagicMock

import pytest

from src.drivers.base import AmmeterDriver, MeasurementSample
from src.testing.sampler import SamplingPlan, resolve_sampling_plan, run_sampling


def make_sample(value=1.0):
    return MeasurementSample(
        value=value, unit="A", timestamp=0.0, device="test",
        raw_response=str(value), error=None,
    )


class FakeClock:
    """Deterministic perf_counter()/sleep() pair for scheduling tests."""

    def __init__(self, start: float = 0.0):
        self.now = start
        self.sleep_calls = []

    def perf_counter(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        assert seconds >= 0, f"slept a negative amount: {seconds}"
        self.sleep_calls.append(seconds)
        self.now += seconds


@pytest.fixture
def fake_clock(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr("src.testing.sampler.time.perf_counter", clock.perf_counter)
    monkeypatch.setattr("src.testing.sampler.time.sleep", clock.sleep)
    monkeypatch.setattr("src.testing.sampler.time.time", lambda: 1000.0)
    return clock


# --- resolve_sampling_plan -------------------------------------------------

def test_resolve_plan_count_only():
    plan = resolve_sampling_plan(
        {"measurements_count": 10, "total_duration_seconds": None, "sampling_frequency_hz": 5.0}
    )
    assert plan.count == 10
    assert plan.rate_hz == 5.0
    assert plan.expected_duration_seconds == 2.0


def test_resolve_plan_duration_only_ceils():
    plan = resolve_sampling_plan(
        {"measurements_count": None, "total_duration_seconds": 3.1, "sampling_frequency_hz": 2.0}
    )
    # 3.1 * 2.0 = 6.2 -> ceil -> 7
    assert plan.count == 7


def test_resolve_plan_count_and_duration_agree():
    plan = resolve_sampling_plan(
        {"measurements_count": 10, "total_duration_seconds": 2.0, "sampling_frequency_hz": 5.0}
    )
    assert plan.count == 10


def test_resolve_plan_count_wins_and_warns_on_disagreement(caplog):
    with caplog.at_level(logging.WARNING):
        plan = resolve_sampling_plan(
            {"measurements_count": 10, "total_duration_seconds": 999.0, "sampling_frequency_hz": 5.0}
        )
    assert plan.count == 10
    assert any("measurements_count wins" in record.message for record in caplog.records)


def test_resolve_plan_missing_rate_raises():
    with pytest.raises(ValueError):
        resolve_sampling_plan({"measurements_count": 10, "total_duration_seconds": None, "sampling_frequency_hz": None})


def test_resolve_plan_missing_count_and_duration_raises():
    with pytest.raises(ValueError):
        resolve_sampling_plan(
            {"measurements_count": None, "total_duration_seconds": None, "sampling_frequency_hz": 5.0}
        )


def test_resolve_plan_zero_rate_raises():
    with pytest.raises(ValueError):
        resolve_sampling_plan(
            {"measurements_count": 10, "total_duration_seconds": None, "sampling_frequency_hz": 0.0}
        )


# --- run_sampling ------------------------------------------------------

def test_run_sampling_takes_exactly_plan_count_samples(fake_clock):
    driver = MagicMock(spec=AmmeterDriver)
    driver.measure.side_effect = lambda: make_sample()
    plan = SamplingPlan(count=5, rate_hz=10.0, expected_duration_seconds=0.5)

    result = run_sampling(driver, plan)

    assert len(result.samples) == 5
    assert len(result.timings) == 5
    assert driver.measure.call_count == 5


def test_run_sampling_scheduled_offsets_are_exact(fake_clock):
    driver = MagicMock(spec=AmmeterDriver)
    driver.measure.side_effect = lambda: make_sample()
    plan = SamplingPlan(count=4, rate_hz=10.0, expected_duration_seconds=0.4)

    result = run_sampling(driver, plan)

    expected = [i / 10.0 for i in range(4)]
    assert [t.scheduled_offset_seconds for t in result.timings] == expected


def test_run_sampling_never_sleeps_negative_and_recovers_from_slow_sample(fake_clock):
    driver = MagicMock(spec=AmmeterDriver)
    call_count = {"n": 0}

    def slow_on_third_call():
        call_count["n"] += 1
        if call_count["n"] == 3:
            fake_clock.now += 0.5  # simulate a slow measurement
        return make_sample()

    driver.measure.side_effect = slow_on_third_call
    plan = SamplingPlan(count=5, rate_hz=10.0, expected_duration_seconds=0.5)

    result = run_sampling(driver, plan)

    assert all(s >= 0 for s in fake_clock.sleep_calls)
    # sample index 3's deadline (0.3) is still anchored to start, not to when
    # sample 2 actually finished (0.7) -- proving the absolute-deadline
    # formula, not a cumulative one, and that the loop doesn't try to sleep
    # to "catch up" (that sleep call must be 0, since we're already late).
    assert result.timings[3].scheduled_offset_seconds == 0.3
    assert fake_clock.sleep_calls[3] == 0.0
    assert result.timings[3].jitter_seconds > 0  # confirms it ran late, not silently reset


def test_run_sampling_rejects_invalid_plan(fake_clock):
    driver = MagicMock(spec=AmmeterDriver)
    with pytest.raises(ValueError):
        run_sampling(driver, SamplingPlan(count=0, rate_hz=10.0, expected_duration_seconds=0.0))
    with pytest.raises(ValueError):
        run_sampling(driver, SamplingPlan(count=5, rate_hz=0.0, expected_duration_seconds=0.0))
