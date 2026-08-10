"""Command-line interface for the ammeter QA framework: run / list / show / compare."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from src.drivers.registry import DriverResolutionError
from src.faults.injector import FaultInjectingDriver, FaultInjectionConfig
from src.reporting.html_report import generate_html_report
from src.testing.store import list_runs, load_run
from src.testing.test_framework import AmmeterTestFramework
from src.utils.config import load_config


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argparse parser.

    Returns:
        An ArgumentParser with `run`, `list`, `show`, and `compare` subcommands.
    """
    parser = argparse.ArgumentParser(prog="ammeter-qa", description="Ammeter QA test runner")
    parser.add_argument("--config", default="config/config.yaml", help="Path to config.yaml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a test against one ammeter or 'all'")
    run_parser.add_argument("target", help="Ammeter name (e.g. 'greenlee') or 'all'")
    run_parser.add_argument(
        "--fault-injection",
        action="store_true",
        help="Wrap each device's driver in a FaultInjectingDriver, using config['fault_injection']",
    )

    list_parser = subparsers.add_parser("list", help="List saved runs")
    list_parser.add_argument("--device", default=None, help="Only show runs for this device")
    list_parser.add_argument("--limit", type=int, default=None, help="Max rows to show")

    show_parser = subparsers.add_parser("show", help="Show one saved run's full details")
    show_parser.add_argument("run_id", help="The run_id to show")

    compare_parser = subparsers.add_parser("compare", help="Compare two saved runs")
    compare_parser.add_argument("run_id_a", help="The first run_id (baseline)")
    compare_parser.add_argument("run_id_b", help="The second run_id (compared against the first)")

    report_parser = subparsers.add_parser("report", help="Render a saved run to a self-contained HTML report")
    report_parser.add_argument("run_id", help="The run_id to render")

    return parser


def _fmt(value: Optional[float], digits: int = 4) -> str:
    """Format an optional float for display, or "n/a" if it's None."""
    return "n/a" if value is None else f"{value:.{digits}f}"


def _cmd_run(args: argparse.Namespace) -> int:
    """Handle `run <target>` [--fault-injection].

    Args:
        args: Parsed CLI arguments (`args.config`, `args.target`,
            `args.fault_injection`).

    Returns:
        0 if every targeted device ran with zero failed samples, else 1.
    """
    try:
        framework = AmmeterTestFramework(config_path=args.config)
    except (FileNotFoundError, yaml.YAMLError) as e:
        print(f"could not load config: {e}", file=sys.stderr)
        return 1

    devices = sorted(framework.config["ammeters"]) if args.target == "all" else [args.target]

    fault_config: Optional[FaultInjectionConfig] = None
    if args.fault_injection:
        try:
            fault_config = FaultInjectionConfig.from_config(
                framework.config.get("fault_injection", {})
            )
        except (KeyError, ValueError) as e:
            print(f"invalid fault_injection config: {e}", file=sys.stderr)
            return 1

    exit_code = 0
    for device in devices:
        driver_wrapper = None
        injected_driver_holder: Dict[str, FaultInjectingDriver] = {}
        if fault_config is not None:
            unit = framework.config["ammeters"].get(device, {}).get("unit", "A")

            def driver_wrapper(driver, _device=device, _unit=unit):
                wrapped = FaultInjectingDriver(driver, fault_config, name=_device, unit=_unit)
                injected_driver_holder["driver"] = wrapped
                return wrapped

        try:
            result = framework.run_test(device, driver_wrapper=driver_wrapper)
        except (KeyError, DriverResolutionError, ValueError, ConnectionError, OSError) as e:
            print(f"[{device}] FAILED: {e}", file=sys.stderr)
            exit_code = 1
            continue

        status = "PASS" if result["success"] else "FAIL"
        line = (
            f"[{device}] {status}  run_id={result['run_id']}  "
            f"samples={result['sample_count']}  success={result['success_count']}  "
            f"failures={result['failure_count']}  mean={_fmt(result['mean'])}  "
            f"cv%={_fmt(result['coefficient_of_variation_percent'])}  "
            f"outliers={result['outlier_count']}"
        )
        if "driver" in injected_driver_holder:
            line += f"  injected_faults={injected_driver_holder['driver'].injected_count}"
        print(line)
        if not result["success"]:
            exit_code = 1

    return exit_code


def _cmd_list(args: argparse.Namespace) -> int:
    """Handle `list`.

    Args:
        args: Parsed CLI arguments (`args.config`, `args.device`, `args.limit`).

    Returns:
        0 (listing runs is never itself a failure condition), except 1 if
        the config can't be loaded.
    """
    try:
        config = load_config(args.config)
    except (FileNotFoundError, yaml.YAMLError) as e:
        print(f"could not load config: {e}", file=sys.stderr)
        return 1

    runs = list_runs(config.get("result_management", {}))
    if args.device:
        runs = [r for r in runs if r["device"] == args.device]
    if args.limit is not None:
        runs = runs[: args.limit]

    if not runs:
        print("no runs found")
        return 0

    print(f"{'RUN ID':<32} {'DEVICE':<10} {'SAMPLES':>7} {'SUCCESS':>7} {'FAIL%':>7} {'MEAN':>10} {'CV%':>8}")
    for r in runs:
        print(
            f"{r['run_id']:<32} {r['device']:<10} {r.get('sample_count', 0):>7} "
            f"{r.get('success_count', 0):>7} {_fmt(r.get('failure_rate_percent'), 1):>7} "
            f"{_fmt(r.get('mean')):>10} {_fmt(r.get('coefficient_of_variation_percent'), 2):>8}"
        )
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    """Handle `show <run_id>`.

    Args:
        args: Parsed CLI arguments (`args.config`, `args.run_id`).

    Returns:
        0 if the run was found and printed, else 1.
    """
    try:
        config = load_config(args.config)
    except (FileNotFoundError, yaml.YAMLError) as e:
        print(f"could not load config: {e}", file=sys.stderr)
        return 1

    result_management = config.get("result_management", {})
    try:
        run = load_run(args.run_id, result_management)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"could not load run '{args.run_id}': {e}", file=sys.stderr)
        return 1

    metadata = run["metadata"]
    analyzed = run["analyzed_results"]
    jitter = metadata["jitter"]
    plan = metadata["sampling_plan"]
    outliers = analyzed["outliers"]

    print(f"Run ID:       {run['run_id']}")
    print(f"Device:       {metadata['device']}")
    print(f"Start:        {metadata['start_time']}")
    print(f"End:          {metadata['end_time']}")
    print(f"Duration (s): {metadata['duration_seconds']:.3f}")
    print()
    print("Sampling plan:")
    print(f"  count={plan['count']}  rate_hz={plan['rate_hz']}")
    print(f"  jitter mean={_fmt(jitter['mean_seconds'], 5)}s  max={_fmt(jitter['max_seconds'], 5)}s")
    print()
    print("Results:")
    print(
        f"  samples={analyzed['sample_count']}  success={analyzed['success_count']}  "
        f"failures={analyzed['failure_count']}"
    )
    print(
        f"  mean={_fmt(analyzed['mean'])}  median={_fmt(analyzed['median'])}  "
        f"stdev={_fmt(analyzed['stdev'])}"
    )
    print(
        f"  min={_fmt(analyzed['min'])}  max={_fmt(analyzed['max'])}  "
        f"cv%={_fmt(analyzed['coefficient_of_variation_percent'])}"
    )
    print()
    print(f"Outliers ({outliers['method']}): count={outliers['count']}  indices={outliers['indices']}")
    if analyzed["notes"]:
        print("Notes:")
        for note in analyzed["notes"]:
            print(f"  - {note}")
    print()

    results_dir = result_management.get("results_dir", "results")
    runs_subdir = result_management.get("runs_subdir", "runs")
    run_path = Path(results_dir) / runs_subdir / f"{run['run_id']}.json"
    print(f"Saved to: {run_path}")

    return 0


_COMPARE_METRICS = [
    ("sample_count", "Samples", 0),
    ("success_count", "Successes", 0),
    ("failure_count", "Failures", 0),
    ("failure_rate_percent", "Failure rate (%)", 2),
    ("mean", "Mean", 4),
    ("median", "Median", 4),
    ("stdev", "Stdev", 4),
    ("min", "Min", 4),
    ("max", "Max", 4),
    ("coefficient_of_variation_percent", "CV (%)", 2),
]


def _cmd_compare(args: argparse.Namespace) -> int:
    """Handle `compare <run_id_a> <run_id_b>`.

    Args:
        args: Parsed CLI arguments (`args.config`, `args.run_id_a`, `args.run_id_b`).

    Returns:
        0 if both runs were found and the comparison table was printed,
        else 1.
    """
    try:
        config = load_config(args.config)
    except (FileNotFoundError, yaml.YAMLError) as e:
        print(f"could not load config: {e}", file=sys.stderr)
        return 1

    result_management = config.get("result_management", {})

    runs: Dict[str, Dict[str, Any]] = {}
    for label, run_id in (("A", args.run_id_a), ("B", args.run_id_b)):
        try:
            runs[label] = load_run(run_id, result_management)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"could not load run {label} ('{run_id}'): {e}", file=sys.stderr)
            return 1

    analyzed_a = runs["A"]["analyzed_results"]
    analyzed_b = runs["B"]["analyzed_results"]

    print(f"Run A: {runs['A']['run_id']}  (device={runs['A']['metadata']['device']})")
    print(f"Run B: {runs['B']['run_id']}  (device={runs['B']['metadata']['device']})")
    print()
    print(f"{'METRIC':<28} {'RUN A':>12} {'RUN B':>12} {'DELTA (B-A)':>14}")
    for key, label, digits in _COMPARE_METRICS:
        a = analyzed_a[key]
        b = analyzed_b[key]
        delta = (b - a) if (a is not None and b is not None) else None
        delta_str = "n/a" if delta is None else f"{delta:+.{digits}f}"
        print(f"{label:<28} {_fmt(a, digits):>12} {_fmt(b, digits):>12} {delta_str:>14}")

    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    """Handle `report <run_id>`.

    Args:
        args: Parsed CLI arguments (`args.config`, `args.run_id`).

    Returns:
        0 if the run was found and the HTML report was written, else 1.
    """
    try:
        config = load_config(args.config)
    except (FileNotFoundError, yaml.YAMLError) as e:
        print(f"could not load config: {e}", file=sys.stderr)
        return 1

    result_management = config.get("result_management", {})
    try:
        run = load_run(args.run_id, result_management)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"could not load run '{args.run_id}': {e}", file=sys.stderr)
        return 1

    results_dir = result_management.get("results_dir", "results")
    output_dir = Path(results_dir) / "reports"
    try:
        report_path = generate_html_report(run, output_dir)
    except OSError as e:
        print(f"could not write report for '{args.run_id}': {e}", file=sys.stderr)
        return 1

    print(f"wrote {report_path}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list to parse; defaults to `sys.argv[1:]`.

    Returns:
        Process exit code (argparse itself exits with 2 on usage errors).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        return _cmd_run(args)
    if args.command == "list":
        return _cmd_list(args)
    if args.command == "show":
        return _cmd_show(args)
    if args.command == "compare":
        return _cmd_compare(args)
    if args.command == "report":
        return _cmd_report(args)

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
