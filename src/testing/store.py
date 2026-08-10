"""Durable JSON persistence for sampling runs, plus a central run index."""

import json
import logging
import platform
import statistics
import tempfile
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.testing.analyzer import AnalysisResult
from src.testing.sampler import SamplingResult

logger = logging.getLogger(__name__)

DEFAULT_RESULTS_DIR = "results"
DEFAULT_RUNS_SUBDIR = "runs"
DEFAULT_INDEX_FILENAME = "index.json"


def generate_run_id(device: str, now: Optional[datetime] = None) -> str:
    """Generate a unique, sortable, filesystem-safe run identifier.

    Args:
        device: The ammeter's config key, e.g. "greenlee".
        now: Timestamp to use; defaults to `datetime.now()`.

    Returns:
        "{YYYYmmdd-HHMMSS}-{device}-{6 hex chars}", e.g.
        "20260810-143210-greenlee-a1b2c3". Sorts naturally by time,
        self-describes its device, and the random suffix breaks ties for
        runs starting in the same second.
    """
    moment = now or datetime.now()
    return f"{moment.strftime('%Y%m%d-%H%M%S')}-{device}-{uuid.uuid4().hex[:6]}"


def build_run_document(
    run_id: str,
    device: str,
    config_snapshot: Dict[str, Any],
    sampling_result: SamplingResult,
    analysis: AnalysisResult,
) -> Dict[str, Any]:
    """Assemble the JSON-serializable document for one completed run.

    Pure function, no I/O.

    Args:
        run_id: This run's identifier, e.g. from `generate_run_id`.
        device: The ammeter's config key.
        config_snapshot: The trimmed config actually used for this run
            (that device's ammeter config plus sampling/analysis config)
            -- not the entire config.yaml.
        sampling_result: The completed SamplingResult.
        analysis: The completed AnalysisResult.

    Returns:
        A dict with "run_id", "metadata" (device, config_used, os,
        python_version, start/end time, duration, sampling_plan, jitter
        summary), "raw_results" (list of MeasurementSample dicts), and
        "analyzed_results" (the AnalysisResult as a dict).
    """
    jitter_values = [t.jitter_seconds for t in sampling_result.timings]
    jitter_summary: Dict[str, Any] = {
        "per_sample_seconds": jitter_values,
        "mean_seconds": statistics.mean(jitter_values) if jitter_values else None,
        "max_seconds": max((abs(j) for j in jitter_values), default=None),
        "stdev_seconds": statistics.stdev(jitter_values) if len(jitter_values) >= 2 else None,
    }

    return {
        "run_id": run_id,
        "metadata": {
            "device": device,
            "config_used": config_snapshot,
            "os": platform.platform(),
            "python_version": platform.python_version(),
            "start_time": sampling_result.start_time,
            "end_time": sampling_result.end_time,
            "duration_seconds": sampling_result.end_time - sampling_result.start_time,
            "sampling_plan": asdict(sampling_result.plan),
            "jitter": jitter_summary,
        },
        "raw_results": [asdict(sample) for sample in sampling_result.samples],
        "analyzed_results": asdict(analysis),
    }


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    """Write `data` as JSON to `path` via write-temp-then-replace.

    Guarantees `path` is either untouched or fully replaced -- never left
    holding a partially-written file.

    Raises:
        OSError: Directory creation or the write/replace failed.
        TypeError: `data` contains something JSON can't serialize.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with open(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp_path.replace(path)
    except (OSError, TypeError) as e:
        logger.error("failed writing %s: %s", path, e)
        tmp_path.unlink(missing_ok=True)
        raise


def _paths(result_management_config: Dict[str, Any]) -> Dict[str, Path]:
    results_dir = Path(result_management_config.get("results_dir", DEFAULT_RESULTS_DIR))
    runs_dir = results_dir / result_management_config.get("runs_subdir", DEFAULT_RUNS_SUBDIR)
    index_path = results_dir / result_management_config.get(
        "index_filename", DEFAULT_INDEX_FILENAME
    )
    return {"results_dir": results_dir, "runs_dir": runs_dir, "index_path": index_path}


def _read_index(index_path: Path) -> Dict[str, Any]:
    """Load the run index, or an empty one if it doesn't exist yet.

    Raises:
        json.JSONDecodeError: The index file exists but isn't valid JSON.
    """
    if not index_path.exists():
        return {"schema_version": 1, "runs": []}
    try:
        with index_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error("index file %s is not valid JSON: %s", index_path, e)
        raise


def save_run(
    run_document: Dict[str, Any], result_management_config: Dict[str, Any]
) -> Path:
    """Persist a run document and update the central run index.

    Args:
        run_document: A document built by `build_run_document`.
        result_management_config: config["result_management"]; keys
            "results_dir", "runs_subdir", "index_filename" (all optional,
            defaulting to "results"/"runs"/"index.json").

    Returns:
        The path the run's JSON file was written to.

    Raises:
        KeyError: `run_document` is missing "run_id" or "metadata".
        OSError: The results directory or files could not be written.
    """
    try:
        run_id = run_document["run_id"]
        metadata = run_document["metadata"]
    except KeyError as e:
        raise KeyError(f"run_document is missing required key {e}") from e

    paths = _paths(result_management_config)
    run_path = paths["runs_dir"] / f"{run_id}.json"
    _atomic_write_json(run_path, run_document)

    analyzed = run_document.get("analyzed_results", {})
    index_entry = {
        "run_id": run_id,
        "device": metadata["device"],
        "start_time": metadata["start_time"],
        "end_time": metadata["end_time"],
        "sample_count": analyzed.get("sample_count"),
        "success_count": analyzed.get("success_count"),
        "failure_rate_percent": analyzed.get("failure_rate_percent"),
        "mean": analyzed.get("mean"),
        "coefficient_of_variation_percent": analyzed.get("coefficient_of_variation_percent"),
    }

    index = _read_index(paths["index_path"])
    index["runs"] = [r for r in index["runs"] if r["run_id"] != run_id] + [index_entry]
    _atomic_write_json(paths["index_path"], index)

    return run_path


def load_run(run_id: str, result_management_config: Dict[str, Any]) -> Dict[str, Any]:
    """Load one previously saved run's full document.

    Args:
        run_id: The run to load.
        result_management_config: config["result_management"].

    Returns:
        The full run document, as saved by `save_run`.

    Raises:
        FileNotFoundError: No run with this run_id has been saved.
        json.JSONDecodeError: The run file exists but isn't valid JSON.
    """
    run_path = _paths(result_management_config)["runs_dir"] / f"{run_id}.json"

    if not run_path.exists():
        raise FileNotFoundError(f"no saved run found for run_id '{run_id}' at {run_path}")

    try:
        with run_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error("run file %s is not valid JSON: %s", run_path, e)
        raise


def list_runs(result_management_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """List all saved runs' index entries, most recent first.

    Args:
        result_management_config: config["result_management"].

    Returns:
        Index entries sorted by start_time descending. Empty list if no
        runs have been saved yet -- not an error.
    """
    index_path = _paths(result_management_config)["index_path"]
    index = _read_index(index_path)
    return sorted(index["runs"], key=lambda entry: entry["start_time"], reverse=True)
