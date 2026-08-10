from src.reporting.html_report import generate_html_report


def _sample(index, value=None, error=None):
    return {
        "value": value,
        "unit": "A",
        "timestamp": float(index),
        "device": "greenlee",
        "raw_response": str(value) if value is not None else None,
        "error": error,
    }


def _run_document(raw_results, run_id="run-1", outlier_indices=None, notes=None):
    values = [r["value"] for r in raw_results if r["error"] is None]
    failure_count = sum(1 for r in raw_results if r["error"] is not None)
    return {
        "run_id": run_id,
        "metadata": {
            "device": "greenlee",
            "duration_seconds": 9.5,
            "jitter": {"mean_seconds": 0.0034, "max_seconds": 0.0051},
        },
        "raw_results": raw_results,
        "analyzed_results": {
            "sample_count": len(raw_results),
            "success_count": len(values),
            "failure_count": failure_count,
            "failure_rate_percent": failure_count / len(raw_results) * 100 if raw_results else 0.0,
            "mean": sum(values) / len(values) if values else None,
            "median": sorted(values)[len(values) // 2] if values else None,
            "stdev": None,
            "min": min(values) if values else None,
            "max": max(values) if values else None,
            "coefficient_of_variation_percent": None,
            "outliers": {
                "method": "iqr",
                "lower_bound": None,
                "upper_bound": None,
                "count": len(outlier_indices or []),
                "indices": outlier_indices or [],
                "values": [],
            },
            "notes": notes or [],
        },
    }


def test_generate_html_report_writes_file_and_returns_its_path(tmp_path):
    raw_results = [_sample(i, value=10.0 + i) for i in range(5)]
    doc = _run_document(raw_results)

    output_path = generate_html_report(doc, tmp_path)

    assert output_path == tmp_path / "run-1.html"
    assert output_path.exists()


def test_report_contains_device_and_stats_and_charts(tmp_path):
    raw_results = [_sample(i, value=10.0 + i) for i in range(5)]
    doc = _run_document(raw_results)

    output_path = generate_html_report(doc, tmp_path)
    content = output_path.read_text(encoding="utf-8")

    assert "greenlee" in content
    assert "run-1" in content
    assert content.count("<svg") == 2  # histogram + time series
    assert "12.0000" in content  # mean of 10..14


def test_report_creates_missing_output_dir(tmp_path):
    raw_results = [_sample(0, value=1.0)]
    doc = _run_document(raw_results)
    nested = tmp_path / "reports" / "nested"

    output_path = generate_html_report(doc, nested)

    assert output_path.exists()
    assert output_path.parent == nested


def test_report_degrades_gracefully_with_zero_successful_samples(tmp_path):
    raw_results = [_sample(i, error="injected fault: timeout") for i in range(4)]
    doc = _run_document(raw_results)

    output_path = generate_html_report(doc, tmp_path)
    content = output_path.read_text(encoding="utf-8")

    assert "No successful samples" in content
    assert content.count("<svg") == 2  # placeholder histogram + still-rendered time series
    assert "point-failure" in content  # failures still marked on the time series


def test_report_marks_outlier_points_distinctly(tmp_path):
    raw_results = [_sample(i, value=10.0 + i) for i in range(5)]
    doc = _run_document(raw_results, outlier_indices=[2])

    output_path = generate_html_report(doc, tmp_path)
    content = output_path.read_text(encoding="utf-8")

    assert "point-outlier" in content


def test_report_includes_notes_when_present(tmp_path):
    raw_results = [_sample(0, value=1.0)]
    doc = _run_document(raw_results, notes=["stdev requires at least 2 samples"])

    output_path = generate_html_report(doc, tmp_path)
    content = output_path.read_text(encoding="utf-8")

    assert "stdev requires at least 2 samples" in content


def test_histogram_bins_parameter_is_respected(tmp_path):
    raw_results = [_sample(i, value=float(i)) for i in range(20)]
    doc = _run_document(raw_results)

    output_path = generate_html_report(doc, tmp_path, histogram_bins=3)
    content = output_path.read_text(encoding="utf-8")

    assert content.count('class="bar"') <= 3
