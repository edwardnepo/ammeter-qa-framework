"""Statistical analysis of a sampling run's MeasurementSamples.

The three ammeter emulators generate independent random parameters with
no shared ground-truth current, so metrological accuracy cannot be
measured here (see docs/DESIGN.md). Only precision and repeatability --
spread, coefficient of variation, and outlier structure -- are
measurable, and that is all this module computes or claims.
"""

import statistics
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from src.drivers.base import MeasurementSample

DEFAULT_IQR_MULTIPLIER = 1.5
DEFAULT_MIN_SAMPLES_FOR_OUTLIER_DETECTION = 4


@dataclass(frozen=True)
class OutlierReport:
    """IQR-based outlier flagging for one run's successful samples.

    Args:
        method: Always "iqr" currently.
        lower_bound: `Q1 - multiplier * IQR`, or None if not computed.
        upper_bound: `Q3 + multiplier * IQR`, or None if not computed.
        count: Number of flagged outliers.
        indices: Positions of flagged samples within the ORIGINAL samples
            list passed to `analyze_samples` (not the success-only
            sublist), so callers can cross-reference raw_results directly.
        values: The flagged samples' values, same order as `indices`.
    """

    method: str
    lower_bound: Optional[float]
    upper_bound: Optional[float]
    count: int
    indices: List[int]
    values: List[float]


@dataclass(frozen=True)
class AnalysisResult:
    """Full statistical summary of one sampling run.

    Every numeric field is None (with a matching entry in `notes`) when it
    can't be computed for this data -- see `analyze_samples` for exactly
    when that happens. Outliers are always flagged, never excluded from
    mean/median/stdev/min/max/CV: this framework can't claim accuracy
    (no ground truth), only honest precision, so headline stats never
    silently drop data.
    """

    sample_count: int
    success_count: int
    failure_count: int
    failure_rate_percent: Optional[float]
    mean: Optional[float]
    median: Optional[float]
    stdev: Optional[float]
    min: Optional[float]
    max: Optional[float]
    coefficient_of_variation_percent: Optional[float]
    outliers: OutlierReport
    notes: List[str]


def analyze_samples(
    samples: List[MeasurementSample],
    outlier_config: Optional[Dict[str, Any]] = None,
) -> AnalysisResult:
    """Compute precision/repeatability statistics for one sampling run.

    mean/median/stdev/min/max/CV are always computed over ALL successful
    samples (`error is None`); IQR outliers are flagged separately and
    never excluded from these headline stats.

    Args:
        samples: The full run, in original order, successes and failures
            interleaved.
        outlier_config: config["analysis"]["outlier_detection"]; keys
            "iqr_multiplier" (default 1.5) and
            "min_samples_for_detection" (default 4).

    Returns:
        An AnalysisResult. Never raises: a field is None with an
        explanatory `notes` entry rather than an exception when it can't
        be computed -- zero successful samples (all fields None); exactly
        one success (stdev/CV None, need >=2 points); mean == 0 (CV None,
        would divide by zero); fewer than
        `min_samples_for_detection` successes (outlier detection skipped).
    """
    outlier_config = outlier_config or {}
    iqr_multiplier = outlier_config.get("iqr_multiplier", DEFAULT_IQR_MULTIPLIER)
    min_samples_for_detection = outlier_config.get(
        "min_samples_for_detection", DEFAULT_MIN_SAMPLES_FOR_OUTLIER_DETECTION
    )

    notes: List[str] = []
    sample_count = len(samples)
    successes: List[Tuple[int, float]] = [
        (i, s.value) for i, s in enumerate(samples) if s.error is None and s.value is not None
    ]
    success_count = len(successes)
    failure_count = sample_count - success_count
    failure_rate_percent = (
        (failure_count / sample_count) * 100.0 if sample_count > 0 else None
    )

    values = [v for _, v in successes]

    mean: Optional[float]
    median: Optional[float]
    stdev: Optional[float]
    min_value: Optional[float]
    max_value: Optional[float]
    cv: Optional[float]

    if success_count == 0:
        notes.append("no successful samples: mean/median/stdev/min/max/CV unavailable")
        mean = median = stdev = min_value = max_value = cv = None
    else:
        mean = statistics.mean(values)
        median = statistics.median(values)
        min_value = min(values)
        max_value = max(values)

        if success_count >= 2:
            stdev = statistics.stdev(values)
        else:
            stdev = None
            notes.append("stdev unavailable: fewer than 2 successful samples")

        if stdev is not None and mean != 0:
            cv = (stdev / mean) * 100.0
        else:
            cv = None
            if stdev is not None and mean == 0:
                notes.append("coefficient_of_variation unavailable: mean is 0")

    outliers = _detect_outliers(successes, iqr_multiplier, min_samples_for_detection, notes)

    return AnalysisResult(
        sample_count=sample_count,
        success_count=success_count,
        failure_count=failure_count,
        failure_rate_percent=failure_rate_percent,
        mean=mean,
        median=median,
        stdev=stdev,
        min=min_value,
        max=max_value,
        coefficient_of_variation_percent=cv,
        outliers=outliers,
        notes=notes,
    )


def _detect_outliers(
    successes: List[Tuple[int, float]],
    iqr_multiplier: float,
    min_samples_for_detection: int,
    notes: List[str],
) -> OutlierReport:
    """Flag IQR outliers among successful (index, value) pairs.

    Appends an explanatory entry to `notes` (mutated in place) when
    detection is skipped for having too few samples.
    """
    if len(successes) < min_samples_for_detection:
        notes.append(
            f"outlier detection skipped: fewer than {min_samples_for_detection} "
            "successful samples"
        )
        return OutlierReport(
            method="iqr", lower_bound=None, upper_bound=None, count=0, indices=[], values=[]
        )

    values = [v for _, v in successes]
    q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive")
    iqr = q3 - q1
    lower_bound = q1 - iqr_multiplier * iqr
    upper_bound = q3 + iqr_multiplier * iqr

    indices: List[int] = []
    outlier_values: List[float] = []
    for idx, value in successes:
        if value < lower_bound or value > upper_bound:
            indices.append(idx)
            outlier_values.append(value)

    return OutlierReport(
        method="iqr",
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        count=len(indices),
        indices=indices,
        values=outlier_values,
    )
