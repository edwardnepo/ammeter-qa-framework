"""Orchestrates one full ammeter test: driver -> sampler -> analyzer -> store."""

from typing import Any, Callable, Dict, Optional

from src.drivers.base import AmmeterDriver
from src.drivers.registry import build_driver
from src.testing.analyzer import analyze_samples
from src.testing.sampler import resolve_sampling_plan, run_sampling
from src.testing.store import build_run_document, generate_run_id, save_run
from src.utils.config import load_config


class AmmeterTestFramework:
    """Top-level entry point tying the core testing layer together."""

    def __init__(self, config_path: str = "config/config.yaml") -> None:
        """
        Args:
            config_path: Path to the YAML config file to load.

        Raises:
            FileNotFoundError: `config_path` doesn't exist.
            yaml.YAMLError: The config file isn't valid YAML.
        """
        self.config = load_config(config_path)

    def run_test(
        self,
        ammeter_type: str,
        driver_wrapper: Optional[Callable[[AmmeterDriver], Any]] = None,
    ) -> Dict[str, Any]:
        """Run one full sampling test against a single configured ammeter.

        Builds the driver via the registry, resolves the sampling plan,
        does a fail-fast reachability preflight (connect, then immediately
        close, before sampling starts), runs absolute-deadline sampling,
        analyzes the resulting samples, persists the full run, and returns
        a summary.

        The preflight connection is closed before sampling begins rather
        than held open for the run's duration: the emulators accept and
        service exactly one connection at a time in a single-threaded
        loop, so an idle connection left open blocks the server's accept
        loop indefinitely, starving every subsequent measurement attempt.

        Args:
            ammeter_type: Key into config["ammeters"], e.g. "greenlee".
            driver_wrapper: Optional hook applied to the freshly built
                driver before the preflight and sampling (e.g. wrapping it
                in a FaultInjectingDriver). Receives the real driver,
                returns the driver to actually use. Defaults to None (no
                wrapping), which preserves existing behavior exactly.

        Returns:
            A summary dict: run_id, device, success (failure_count == 0),
            sample_count, success_count, failure_count,
            failure_rate_percent, mean, median, stdev, min, max,
            coefficient_of_variation_percent, outlier_count, start_time,
            end_time, duration_seconds, result_path.

        Raises:
            KeyError: `ammeter_type` is not a configured ammeter, or the
                config is missing "testing.sampling".
            DriverResolutionError: The ammeter's "driver" path in config
                can't be resolved to a class.
            ValueError: The sampling config is invalid (e.g. no rate set).
            ConnectionError: The device is unreachable after retries.
            OSError: The run could not be written to disk.
        """
        try:
            ammeter_config = self.config["ammeters"][ammeter_type]
        except KeyError as e:
            raise KeyError(f"unknown ammeter_type '{ammeter_type}'") from e

        sampling_config = self.config["testing"]["sampling"]
        analysis_config = self.config.get("analysis", {})
        outlier_config = analysis_config.get("outlier_detection")
        result_management_config = self.config.get("result_management", {})

        plan = resolve_sampling_plan(sampling_config)
        driver = build_driver(ammeter_type, ammeter_config)
        if driver_wrapper is not None:
            driver = driver_wrapper(driver)

        driver.connect()
        driver.close()
        sampling_result = run_sampling(driver, plan)

        analysis = analyze_samples(sampling_result.samples, outlier_config)

        run_id = generate_run_id(ammeter_type)
        config_snapshot = {
            "ammeter": ammeter_config,
            "sampling": sampling_config,
            "analysis": analysis_config,
        }
        run_document = build_run_document(
            run_id, ammeter_type, config_snapshot, sampling_result, analysis
        )
        result_path = save_run(run_document, result_management_config)

        return {
            "run_id": run_id,
            "device": ammeter_type,
            "success": analysis.failure_count == 0,
            "sample_count": analysis.sample_count,
            "success_count": analysis.success_count,
            "failure_count": analysis.failure_count,
            "failure_rate_percent": analysis.failure_rate_percent,
            "mean": analysis.mean,
            "median": analysis.median,
            "stdev": analysis.stdev,
            "min": analysis.min,
            "max": analysis.max,
            "coefficient_of_variation_percent": analysis.coefficient_of_variation_percent,
            "outlier_count": analysis.outliers.count,
            "start_time": sampling_result.start_time,
            "end_time": sampling_result.end_time,
            "duration_seconds": sampling_result.end_time - sampling_result.start_time,
            "result_path": str(result_path),
        }
