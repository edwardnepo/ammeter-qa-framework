import json
from datetime import datetime

import pytest

from src.drivers.base import MeasurementSample
from src.testing.analyzer import AnalysisResult, OutlierReport
from src.testing.sampler import SamplingPlan, SamplingResult, SampleTiming
from src.testing.store import (
    build_run_document,
    generate_run_id,
    list_runs,
    load_run,
    save_run,
)


def make_sampling_result(count=3):
    plan = SamplingPlan(count=count, rate_hz=2.0, expected_duration_seconds=count / 2.0)
    samples = [
        MeasurementSample(
            value=10.0 + i, unit="A", timestamp=100.0 + i, device="greenlee",
            raw_response=str(10.0 + i), error=None,
        )
        for i in range(count)
    ]
    timings = [
        SampleTiming(index=i, scheduled_offset_seconds=i / 2.0, actual_offset_seconds=i / 2.0 + 0.001, jitter_seconds=0.001)
        for i in range(count)
    ]
    return SamplingResult(samples=samples, timings=timings, plan=plan, start_time=100.0, end_time=100.0 + count / 2.0)


def make_analysis_result():
    return AnalysisResult(
        sample_count=3, success_count=3, failure_count=0, failure_rate_percent=0.0,
        mean=11.0, median=11.0, stdev=1.0, min=10.0, max=12.0,
        coefficient_of_variation_percent=9.09,
        outliers=OutlierReport(method="iqr", lower_bound=8.0, upper_bound=14.0, count=0, indices=[], values=[]),
        notes=[],
    )


@pytest.fixture
def result_management_config(tmp_path):
    return {
        "results_dir": str(tmp_path / "results"),
        "runs_subdir": "runs",
        "index_filename": "index.json",
    }


# --- generate_run_id -------------------------------------------------------

def test_generate_run_id_format():
    run_id = generate_run_id("greenlee", now=datetime(2026, 8, 10, 14, 32, 10))
    assert run_id.startswith("20260810-143210-greenlee-")
    suffix = run_id.split("-")[-1]
    assert len(suffix) == 6


def test_generate_run_id_is_unique_across_rapid_calls():
    ids = {generate_run_id("greenlee") for _ in range(20)}
    assert len(ids) == 20


# --- build_run_document -----------------------------------------------------

def test_build_run_document_shape():
    sampling_result = make_sampling_result()
    analysis = make_analysis_result()
    doc = build_run_document(
        run_id="20260810-143210-greenlee-abc123",
        device="greenlee",
        config_snapshot={"ammeter": {"port": 5000}},
        sampling_result=sampling_result,
        analysis=analysis,
    )

    assert doc["run_id"] == "20260810-143210-greenlee-abc123"
    assert doc["metadata"]["device"] == "greenlee"
    assert doc["metadata"]["config_used"] == {"ammeter": {"port": 5000}}
    assert doc["metadata"]["start_time"] == 100.0
    assert doc["metadata"]["sampling_plan"]["count"] == 3
    assert len(doc["metadata"]["jitter"]["per_sample_seconds"]) == 3
    assert len(doc["raw_results"]) == 3
    assert doc["raw_results"][0]["value"] == 10.0
    assert doc["analyzed_results"]["mean"] == 11.0
    assert doc["analyzed_results"]["outliers"]["method"] == "iqr"
    # must be JSON-serializable as-is
    json.dumps(doc)


# --- save_run / load_run / list_runs ---------------------------------------

def test_save_and_load_round_trip(result_management_config):
    doc = build_run_document(
        run_id="run-1", device="greenlee", config_snapshot={},
        sampling_result=make_sampling_result(), analysis=make_analysis_result(),
    )

    path = save_run(doc, result_management_config)
    assert path.exists()

    loaded = load_run("run-1", result_management_config)
    assert loaded == doc


def test_index_accumulates_and_overwrites_by_run_id(result_management_config):
    doc_a = build_run_document(
        run_id="run-a", device="greenlee", config_snapshot={},
        sampling_result=make_sampling_result(), analysis=make_analysis_result(),
    )
    doc_b = build_run_document(
        run_id="run-b", device="entes", config_snapshot={},
        sampling_result=make_sampling_result(), analysis=make_analysis_result(),
    )
    save_run(doc_a, result_management_config)
    save_run(doc_b, result_management_config)

    runs = list_runs(result_management_config)
    assert {r["run_id"] for r in runs} == {"run-a", "run-b"}

    # re-saving run-a should update, not duplicate, its index entry
    save_run(doc_a, result_management_config)
    runs_after = list_runs(result_management_config)
    assert len(runs_after) == 2


def test_list_runs_sorted_most_recent_first(result_management_config):
    older = make_sampling_result()
    newer = make_sampling_result()
    doc_old = build_run_document(
        run_id="run-old", device="greenlee", config_snapshot={},
        sampling_result=SamplingResult(older.samples, older.timings, older.plan, start_time=1.0, end_time=2.0),
        analysis=make_analysis_result(),
    )
    doc_new = build_run_document(
        run_id="run-new", device="greenlee", config_snapshot={},
        sampling_result=SamplingResult(newer.samples, newer.timings, newer.plan, start_time=100.0, end_time=101.0),
        analysis=make_analysis_result(),
    )
    save_run(doc_old, result_management_config)
    save_run(doc_new, result_management_config)

    runs = list_runs(result_management_config)
    assert [r["run_id"] for r in runs] == ["run-new", "run-old"]


def test_list_runs_empty_when_nothing_saved(result_management_config):
    assert list_runs(result_management_config) == []


def test_load_run_missing_raises_file_not_found(result_management_config):
    with pytest.raises(FileNotFoundError):
        load_run("does-not-exist", result_management_config)


def test_load_run_corrupt_file_raises_json_decode_error(result_management_config):
    doc = build_run_document(
        run_id="run-corrupt", device="greenlee", config_snapshot={},
        sampling_result=make_sampling_result(), analysis=make_analysis_result(),
    )
    path = save_run(doc, result_management_config)
    path.write_text("{ this is not valid json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        load_run("run-corrupt", result_management_config)


def test_save_run_missing_required_key_raises_keyerror(result_management_config):
    with pytest.raises(KeyError):
        save_run({"not_run_id": True}, result_management_config)


def test_atomic_write_leaves_existing_file_untouched_on_failure(monkeypatch, result_management_config):
    doc = build_run_document(
        run_id="run-atomic", device="greenlee", config_snapshot={},
        sampling_result=make_sampling_result(), analysis=make_analysis_result(),
    )
    path = save_run(doc, result_management_config)
    original_content = path.read_text(encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("src.testing.store.json.dump", boom)

    other_doc = build_run_document(
        run_id="run-atomic", device="greenlee", config_snapshot={"changed": True},
        sampling_result=make_sampling_result(), analysis=make_analysis_result(),
    )
    with pytest.raises(OSError):
        save_run(other_doc, result_management_config)

    assert path.read_text(encoding="utf-8") == original_content
