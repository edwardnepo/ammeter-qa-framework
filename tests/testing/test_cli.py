from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src import cli
from src.drivers.base import MeasurementSample
from src.testing.analyzer import AnalysisResult, OutlierReport
from src.testing.sampler import SamplingPlan, SamplingResult, SampleTiming
from src.testing.store import build_run_document, save_run


def _seed_run(result_management, run_id="run-1", device="greenlee", mean=10.0, failure_count=0):
    plan = SamplingPlan(count=1, rate_hz=1.0, expected_duration_seconds=1.0)
    samples = [
        MeasurementSample(
            value=mean, unit="A", timestamp=0.0, device=device, raw_response=str(mean), error=None
        )
    ]
    timings = [
        SampleTiming(index=0, scheduled_offset_seconds=0.0, actual_offset_seconds=0.0, jitter_seconds=0.0)
    ]
    sampling_result = SamplingResult(
        samples=samples, timings=timings, plan=plan, start_time=0.0, end_time=1.0
    )
    analysis = AnalysisResult(
        sample_count=1, success_count=1 - failure_count, failure_count=failure_count,
        failure_rate_percent=failure_count * 100.0,
        mean=mean, median=mean, stdev=None, min=mean, max=mean,
        coefficient_of_variation_percent=None,
        outliers=OutlierReport(method="iqr", lower_bound=None, upper_bound=None, count=0, indices=[], values=[]),
        notes=[],
    )
    doc = build_run_document(run_id, device, {}, sampling_result, analysis)
    return save_run(doc, result_management)


# --- run ---------------------------------------------------------------

@pytest.fixture
def fake_framework(monkeypatch):
    instance = MagicMock()
    instance.config = {"ammeters": {"greenlee": {}, "entes": {}, "circutor": {}}}
    monkeypatch.setattr("src.cli.AmmeterTestFramework", MagicMock(return_value=instance))
    return instance


def canned_result(run_id="run-1", device="greenlee", success=True, failure_count=0):
    return {
        "run_id": run_id, "device": device, "success": success,
        "sample_count": 5, "success_count": 5 - failure_count, "failure_count": failure_count,
        "failure_rate_percent": failure_count / 5 * 100,
        "mean": 10.0, "median": 10.0, "stdev": 0.1, "min": 9.8, "max": 10.2,
        "coefficient_of_variation_percent": 1.0, "outlier_count": 0,
        "start_time": 0.0, "end_time": 1.0, "duration_seconds": 1.0,
        "result_path": "results/runs/run-1.json",
    }


def test_cmd_run_happy_path(fake_framework, capsys):
    fake_framework.run_test.return_value = canned_result()
    exit_code = cli.main(["run", "greenlee"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "PASS" in out
    assert "run-1" in out


def test_cmd_run_failure_path(fake_framework, capsys):
    fake_framework.run_test.return_value = canned_result(success=False, failure_count=2)
    exit_code = cli.main(["run", "greenlee"])
    assert exit_code == 1
    assert "FAIL" in capsys.readouterr().out


def test_cmd_run_all_continues_on_error(fake_framework, capsys):
    def side_effect(device, driver_wrapper=None):
        if device == "entes":
            raise ConnectionError("unreachable")
        return canned_result(run_id=f"run-{device}", device=device)

    fake_framework.run_test.side_effect = side_effect

    exit_code = cli.main(["run", "all"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "circutor" in captured.out  # ran despite entes failing
    assert "greenlee" in captured.out  # continued past entes
    assert "entes" in captured.err


def test_cmd_run_without_fault_injection_flag_passes_none_wrapper(fake_framework, capsys):
    fake_framework.run_test.return_value = canned_result()

    cli.main(["run", "greenlee"])

    _, kwargs = fake_framework.run_test.call_args
    assert kwargs.get("driver_wrapper") is None
    assert "injected_faults" not in capsys.readouterr().out


def test_cmd_run_fault_injection_invalid_config_exits_1(fake_framework, capsys):
    # fake_framework.config carries no "fault_injection" section at all.
    exit_code = cli.main(["run", "greenlee", "--fault-injection"])

    assert exit_code == 1
    assert "fault_injection" in capsys.readouterr().err
    fake_framework.run_test.assert_not_called()


def test_cmd_run_fault_injection_prints_injected_count(fake_framework, capsys):
    fake_framework.config["fault_injection"] = {
        "fault_rate": 1.0,
        "seed": 1,
        "fault_types": ["timeout"],
        "injected_timeout_seconds": 0.001,
    }

    def side_effect(device, driver_wrapper=None):
        assert driver_wrapper is not None
        driver_wrapper(MagicMock())  # simulate what real run_test does with the hook
        return canned_result()

    fake_framework.run_test.side_effect = side_effect

    exit_code = cli.main(["run", "greenlee", "--fault-injection"])

    assert exit_code == 0
    assert "injected_faults=0" in capsys.readouterr().out


def test_no_command_exits_2():
    with pytest.raises(SystemExit) as exc_info:
        cli.main([])
    assert exc_info.value.code == 2


def test_unknown_command_exits_2():
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["bogus"])
    assert exc_info.value.code == 2


# --- list / show ---------------------------------------------------------

@pytest.fixture
def seeded_config(tmp_path, monkeypatch):
    result_management = {
        "results_dir": str(tmp_path / "results"),
        "runs_subdir": "runs",
        "index_filename": "index.json",
    }
    config = {"result_management": result_management}
    monkeypatch.setattr("src.cli.load_config", lambda path: config)
    return config


def test_cmd_list_empty(seeded_config, capsys):
    exit_code = cli.main(["list"])
    assert exit_code == 0
    assert "no runs found" in capsys.readouterr().out


def test_cmd_list_populated(seeded_config, capsys):
    _seed_run(seeded_config["result_management"], run_id="run-1", device="greenlee")
    exit_code = cli.main(["list"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "run-1" in out
    assert "greenlee" in out


def test_cmd_show_found(seeded_config, capsys):
    _seed_run(seeded_config["result_management"], run_id="run-2", device="entes")
    exit_code = cli.main(["show", "run-2"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "run-2" in out
    assert "entes" in out


def test_cmd_show_not_found(seeded_config, capsys):
    exit_code = cli.main(["show", "does-not-exist"])
    assert exit_code == 1
    assert "could not load run" in capsys.readouterr().err


# --- compare ---------------------------------------------------------------


def test_cmd_compare_prints_metrics_and_delta(seeded_config, capsys):
    _seed_run(seeded_config["result_management"], run_id="run-a", device="greenlee", mean=10.0)
    _seed_run(seeded_config["result_management"], run_id="run-b", device="greenlee", mean=12.0)

    exit_code = cli.main(["compare", "run-a", "run-b"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "run-a" in out and "run-b" in out
    assert "10.0000" in out
    assert "12.0000" in out
    assert "+2.0000" in out  # delta = B - A


def test_cmd_compare_run_a_not_found(seeded_config, capsys):
    _seed_run(seeded_config["result_management"], run_id="run-b")

    exit_code = cli.main(["compare", "does-not-exist", "run-b"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "could not load run A" in err
    assert "does-not-exist" in err


def test_cmd_compare_run_b_not_found(seeded_config, capsys):
    _seed_run(seeded_config["result_management"], run_id="run-a")

    exit_code = cli.main(["compare", "run-a", "does-not-exist"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "could not load run B" in err


def test_cmd_compare_config_load_failure_exits_1(monkeypatch, capsys):
    monkeypatch.setattr(
        "src.cli.load_config", lambda path: (_ for _ in ()).throw(FileNotFoundError("missing"))
    )

    exit_code = cli.main(["compare", "run-a", "run-b"])

    assert exit_code == 1
    assert "could not load config" in capsys.readouterr().err


# --- report ------------------------------------------------------------


def test_cmd_report_writes_html(seeded_config, capsys):
    _seed_run(seeded_config["result_management"], run_id="run-3", device="greenlee")

    exit_code = cli.main(["report", "run-3"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "run-3" in out
    report_path = Path(seeded_config["result_management"]["results_dir"]) / "reports" / "run-3.html"
    assert report_path.exists()
    assert "run-3" in report_path.read_text(encoding="utf-8")


def test_cmd_report_run_not_found(seeded_config, capsys):
    exit_code = cli.main(["report", "does-not-exist"])

    assert exit_code == 1
    assert "could not load run 'does-not-exist'" in capsys.readouterr().err


def test_cmd_report_config_load_failure_exits_1(monkeypatch, capsys):
    monkeypatch.setattr(
        "src.cli.load_config", lambda path: (_ for _ in ()).throw(FileNotFoundError("missing"))
    )

    exit_code = cli.main(["report", "run-1"])

    assert exit_code == 1
    assert "could not load config" in capsys.readouterr().err
