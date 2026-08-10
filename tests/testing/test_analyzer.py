from src.drivers.base import MeasurementSample
from src.testing.analyzer import analyze_samples


def sample(value=None, error=None, device="test"):
    return MeasurementSample(
        value=value, unit="A", timestamp=0.0, device=device,
        raw_response=str(value) if value is not None else None, error=error,
    )


def test_empty_list():
    result = analyze_samples([])
    assert result.sample_count == 0
    assert result.success_count == 0
    assert result.failure_count == 0
    assert result.failure_rate_percent is None
    assert result.mean is None
    assert result.outliers.count == 0


def test_all_failed():
    samples = [sample(error="timeout") for _ in range(3)]
    result = analyze_samples(samples)
    assert result.sample_count == 3
    assert result.success_count == 0
    assert result.failure_count == 3
    assert result.failure_rate_percent == 100.0
    assert result.mean is None
    assert any("no successful samples" in n for n in result.notes)


def test_single_success_no_stdev_or_cv():
    result = analyze_samples([sample(value=5.0)])
    assert result.success_count == 1
    assert result.mean == 5.0
    assert result.median == 5.0
    assert result.min == 5.0
    assert result.max == 5.0
    assert result.stdev is None
    assert result.coefficient_of_variation_percent is None
    assert any("fewer than 2" in n for n in result.notes)


def test_two_successes_computes_stdev_and_cv():
    result = analyze_samples([sample(value=4.0), sample(value=6.0)])
    assert result.success_count == 2
    assert result.mean == 5.0
    assert result.stdev is not None
    assert result.coefficient_of_variation_percent is not None


def test_mean_zero_makes_cv_none():
    result = analyze_samples([sample(value=-1.0), sample(value=1.0)])
    assert result.mean == 0.0
    assert result.stdev is not None
    assert result.coefficient_of_variation_percent is None
    assert any("mean is 0" in n for n in result.notes)


def test_fewer_than_min_samples_skips_outlier_detection():
    samples = [sample(value=v) for v in [1.0, 2.0, 3.0]]
    result = analyze_samples(samples, outlier_config={"min_samples_for_detection": 4})
    assert result.outliers.count == 0
    assert result.outliers.lower_bound is None
    assert any("outlier detection skipped" in n for n in result.notes)


def test_known_outlier_is_flagged_but_not_excluded_from_headline_stats():
    # tight cluster around 10, one obvious outlier at 100
    values = [10.0, 10.1, 9.9, 10.2, 9.8, 100.0]
    samples = [sample(value=v) for v in values]

    result = analyze_samples(samples, outlier_config={"min_samples_for_detection": 4})

    assert result.outliers.count == 1
    assert result.outliers.values == [100.0]
    # index 5 is the outlier's position in the original samples list
    assert result.outliers.indices == [5]
    # headline stats still include the outlier -- flagged, not excluded
    import statistics as _statistics
    assert result.mean == _statistics.mean(values)
    assert result.max == 100.0


def test_outlier_indices_refer_to_original_list_with_interleaved_failures():
    samples = [
        sample(value=10.0),          # index 0
        sample(error="timeout"),     # index 1 (failure)
        sample(value=10.1),          # index 2
        sample(value=9.9),           # index 3
        sample(error="timeout"),     # index 4 (failure)
        sample(value=100.0),         # index 5 (outlier)
        sample(value=10.2),          # index 6
    ]
    result = analyze_samples(samples, outlier_config={"min_samples_for_detection": 4})
    assert result.sample_count == 7
    assert result.success_count == 5
    assert result.failure_count == 2
    assert result.outliers.indices == [5]
