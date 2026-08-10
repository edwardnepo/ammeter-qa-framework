from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.drivers.base import AmmeterDriver, MeasurementSample
from src.testing.test_framework import AmmeterTestFramework


def make_sample(value=10.0, error=None):
    return MeasurementSample(
        value=value, unit="A", timestamp=0.0, device="greenlee",
        raw_response=str(value) if value is not None else None, error=error,
    )


@pytest.fixture
def full_config(tmp_path):
    return {
        "testing": {
            "sampling": {
                "measurements_count": 3,
                "total_duration_seconds": None,
                "sampling_frequency_hz": 100.0,
            }
        },
        "ammeters": {
            "greenlee": {
                "driver": "src.drivers.greenlee.GreenleeDriver",
                "host": "localhost", "port": 5000,
                "command": "MEASURE_GREENLEE -get_measurement",
                "timeout_seconds": 1.0, "retries": 1, "retry_backoff_seconds": 0.0,
            },
        },
        "analysis": {
            "outlier_detection": {"iqr_multiplier": 1.5, "min_samples_for_detection": 4},
        },
        "result_management": {
            "results_dir": str(tmp_path / "results"),
            "runs_subdir": "runs",
            "index_filename": "index.json",
        },
    }


@pytest.fixture
def framework(monkeypatch, full_config):
    monkeypatch.setattr(
        "src.testing.test_framework.load_config", lambda path: full_config
    )
    return AmmeterTestFramework(config_path="unused")


def mock_driver(measure_results):
    driver = MagicMock(spec=AmmeterDriver)
    driver.measure.side_effect = measure_results
    return driver


def test_run_test_returns_expected_summary_shape(monkeypatch, framework):
    driver = mock_driver([make_sample(10.0), make_sample(11.0), make_sample(12.0)])
    monkeypatch.setattr(
        "src.testing.test_framework.build_driver", lambda name, cfg: driver
    )

    result = framework.run_test("greenlee")

    assert result["device"] == "greenlee"
    assert result["sample_count"] == 3
    assert result["success_count"] == 3
    assert result["failure_count"] == 0
    assert result["success"] is True
    assert result["mean"] == 11.0
    assert "run_id" in result and result["run_id"].startswith("2")
    assert Path(result["result_path"]).exists()


def test_run_test_closes_preflight_connection_before_sampling(monkeypatch, framework):
    # Regression guard: the emulators serve one connection at a time in a
    # single-threaded loop, so holding the preflight connection open across
    # the whole sampling run (e.g. via `with driver:`) starves every
    # measure() call. connect() and close() must both happen before the
    # first measure() call.
    driver = mock_driver([make_sample(10.0), make_sample(11.0), make_sample(12.0)])
    monkeypatch.setattr(
        "src.testing.test_framework.build_driver", lambda name, cfg: driver
    )

    framework.run_test("greenlee")

    call_names = [call[0] for call in driver.mock_calls]
    assert "connect" in call_names and "close" in call_names and "measure" in call_names
    assert call_names.index("connect") < call_names.index("close")
    assert call_names.index("close") < call_names.index("measure")


def test_run_test_marks_success_false_when_any_sample_fails(monkeypatch, framework):
    driver = mock_driver([make_sample(10.0), make_sample(error="timeout"), make_sample(12.0)])
    monkeypatch.setattr(
        "src.testing.test_framework.build_driver", lambda name, cfg: driver
    )

    result = framework.run_test("greenlee")

    assert result["failure_count"] == 1
    assert result["success"] is False


def test_run_test_unknown_ammeter_raises_keyerror(framework):
    with pytest.raises(KeyError):
        framework.run_test("nonexistent_vendor")


def test_run_test_propagates_connection_error(monkeypatch, framework):
    driver = MagicMock(spec=AmmeterDriver)
    driver.connect.side_effect = ConnectionError("device unreachable")
    monkeypatch.setattr(
        "src.testing.test_framework.build_driver", lambda name, cfg: driver
    )

    with pytest.raises(ConnectionError):
        framework.run_test("greenlee")


def test_run_test_persists_a_loadable_run(monkeypatch, framework, full_config):
    driver = mock_driver([make_sample(10.0), make_sample(11.0), make_sample(12.0)])
    monkeypatch.setattr(
        "src.testing.test_framework.build_driver", lambda name, cfg: driver
    )

    result = framework.run_test("greenlee")

    from src.testing.store import load_run
    loaded = load_run(result["run_id"], full_config["result_management"])
    assert loaded["run_id"] == result["run_id"]
    assert loaded["analyzed_results"]["success_count"] == 3
