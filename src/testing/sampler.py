"""Repeated ammeter sampling with absolute-deadline scheduling.

Uses `next_t = start + i / rate` plus `time.sleep(max(0, next_t - now))`
rather than a naive cumulative `time.sleep(1/rate)`, which would drift as
each iteration's own overhead accumulates across the run.
"""

import logging
import math
import time
from dataclasses import dataclass
from typing import Any, Dict, List

from src.drivers.base import AmmeterDriver, MeasurementSample

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SamplingPlan:
    """A resolved, concrete sampling schedule.

    Args:
        count: Number of samples to take.
        rate_hz: Sampling rate in Hz.
        expected_duration_seconds: `count / rate_hz`, informational only.
    """

    count: int
    rate_hz: float
    expected_duration_seconds: float


def resolve_sampling_plan(sampling_config: Dict[str, Any]) -> SamplingPlan:
    """Resolve config.yaml's testing.sampling block into a concrete plan.

    `sampling_frequency_hz` is always required. If `measurements_count` is
    set, it determines the plan's count outright; `total_duration_seconds`,
    if also set, is only cross-checked against count/rate and logged as a
    warning on disagreement — it never overrides count. If
    `measurements_count` is unset, count is derived as
    `ceil(total_duration_seconds * sampling_frequency_hz)`, minimum 1.

    Args:
        sampling_config: config["testing"]["sampling"] — a dict with keys
            "measurements_count" (Optional[int]),
            "total_duration_seconds" (Optional[float]),
            "sampling_frequency_hz" (float, required, > 0).

    Returns:
        A SamplingPlan with a concrete integer count.

    Raises:
        ValueError: rate_hz missing or <= 0; neither count nor duration
            set; or the resolved count is < 1.
    """
    rate_hz = sampling_config.get("sampling_frequency_hz")
    if rate_hz is None or rate_hz <= 0:
        raise ValueError(f"sampling_frequency_hz must be > 0, got {rate_hz!r}")

    count = sampling_config.get("measurements_count")
    duration = sampling_config.get("total_duration_seconds")

    if count is not None:
        resolved_count = int(count)
        if duration is not None:
            expected_duration = resolved_count / rate_hz
            if abs(expected_duration - duration) > (1.0 / rate_hz):
                logger.warning(
                    "sampling config: measurements_count=%s at rate=%sHz "
                    "implies %.3fs, but total_duration_seconds=%s was also "
                    "set; measurements_count wins, duration is ignored",
                    count, rate_hz, expected_duration, duration,
                )
    elif duration is not None:
        resolved_count = max(1, math.ceil(duration * rate_hz))
    else:
        raise ValueError(
            "sampling config must set at least one of measurements_count "
            "or total_duration_seconds"
        )

    if resolved_count < 1:
        raise ValueError(f"resolved sample count must be >= 1, got {resolved_count}")

    return SamplingPlan(
        count=resolved_count,
        rate_hz=rate_hz,
        expected_duration_seconds=resolved_count / rate_hz,
    )


@dataclass(frozen=True)
class SampleTiming:
    """Scheduled-vs-actual timing for one sample.

    Args:
        index: 0-based position of this sample within the run.
        scheduled_offset_seconds: `index / rate_hz` — the deadline.
        actual_offset_seconds: Elapsed time since the run started, measured
            immediately after waking from the scheduling sleep.
        jitter_seconds: `actual_offset_seconds - scheduled_offset_seconds`.
    """

    index: int
    scheduled_offset_seconds: float
    actual_offset_seconds: float
    jitter_seconds: float


@dataclass(frozen=True)
class SamplingResult:
    """The full output of one sampling run.

    Args:
        samples: One MeasurementSample per sample taken, in order.
        timings: One SampleTiming per sample taken, in order.
        plan: The SamplingPlan this run executed.
        start_time: `time.time()` epoch seconds when sampling began.
        end_time: `time.time()` epoch seconds when sampling finished.
    """

    samples: List[MeasurementSample]
    timings: List[SampleTiming]
    plan: SamplingPlan
    start_time: float
    end_time: float


def run_sampling(driver: AmmeterDriver, plan: SamplingPlan) -> SamplingResult:
    """Take `plan.count` samples from `driver` at `plan.rate_hz`.

    Uses absolute-deadline scheduling: `next_t = start + i / rate`,
    `time.sleep(max(0, next_t - time.perf_counter()))`. Jitter is measured
    immediately after waking from that sleep, before calling
    `driver.measure()`, so it reflects scheduler drift rather than TCP
    round-trip time.

    The caller owns the driver's connection lifecycle (e.g. via
    `with driver:`); this function only calls `driver.measure()`, which
    manages its own socket per attempt and never raises for network
    failures.

    Args:
        driver: A driver to sample from.
        plan: The resolved sampling plan to execute.

    Returns:
        A SamplingResult with exactly `plan.count` samples and timings.

    Raises:
        ValueError: `plan.count` < 1 or `plan.rate_hz` <= 0.
    """
    if plan.count < 1:
        raise ValueError(f"plan.count must be >= 1, got {plan.count}")
    if plan.rate_hz <= 0:
        raise ValueError(f"plan.rate_hz must be > 0, got {plan.rate_hz}")

    samples: List[MeasurementSample] = []
    timings: List[SampleTiming] = []

    start_perf = time.perf_counter()
    start_time = time.time()

    for i in range(plan.count):
        scheduled = i / plan.rate_hz
        next_t = start_perf + scheduled
        time.sleep(max(0.0, next_t - time.perf_counter()))
        actual = time.perf_counter() - start_perf
        timings.append(
            SampleTiming(
                index=i,
                scheduled_offset_seconds=scheduled,
                actual_offset_seconds=actual,
                jitter_seconds=actual - scheduled,
            )
        )
        samples.append(driver.measure())

    end_time = time.time()

    return SamplingResult(
        samples=samples,
        timings=timings,
        plan=plan,
        start_time=start_time,
        end_time=end_time,
    )
