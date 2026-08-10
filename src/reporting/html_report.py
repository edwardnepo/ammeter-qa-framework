"""Dependency-free HTML report generator: stats table plus hand-rolled SVG charts.

Pure stdlib (string templates + inline <svg>, no matplotlib/seaborn/etc.),
per the project rule that anything beyond stdlib must be isolated in
`reporting/` and degrade gracefully when absent — this module needs
nothing beyond stdlib at all.
"""

import html as html_lib
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set


def _fmt(value: Optional[float], digits: int = 4) -> str:
    """Format an optional float for display, or "n/a" if it's None."""
    return "n/a" if value is None else f"{value:.{digits}f}"


def _empty_svg(width: int, height: int, message: str) -> str:
    """A placeholder chart for when there's no data to plot."""
    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="{html_lib.escape(message)}">'
        f'<text x="{width / 2:.1f}" y="{height / 2:.1f}" text-anchor="middle" '
        f'class="empty-message">{html_lib.escape(message)}</text>'
        f"</svg>"
    )


def _build_stats_table(analyzed: Dict[str, Any]) -> str:
    """Render analyzed_results into an HTML stats table (+ notes list)."""
    outliers = analyzed["outliers"]
    rows = [
        ("Samples", str(analyzed["sample_count"])),
        ("Successes", str(analyzed["success_count"])),
        ("Failures", str(analyzed["failure_count"])),
        ("Failure rate (%)", _fmt(analyzed["failure_rate_percent"], 2)),
        ("Mean", _fmt(analyzed["mean"])),
        ("Median", _fmt(analyzed["median"])),
        ("Stdev", _fmt(analyzed["stdev"])),
        ("Min", _fmt(analyzed["min"])),
        ("Max", _fmt(analyzed["max"])),
        ("Coefficient of variation (%)", _fmt(analyzed["coefficient_of_variation_percent"], 2)),
        (f"Outliers ({outliers['method']})", str(outliers["count"])),
    ]
    body = "\n".join(
        f"<tr><th>{html_lib.escape(label)}</th><td>{html_lib.escape(value)}</td></tr>"
        for label, value in rows
    )
    table = f'<table class="stats">\n{body}\n</table>'

    notes = analyzed.get("notes") or []
    if not notes:
        return table
    items = "\n".join(f"<li>{html_lib.escape(note)}</li>" for note in notes)
    return f"{table}\n<h3>Notes</h3>\n<ul>{items}</ul>"


def _build_histogram_svg(values: Sequence[float], bins: int, width: int, height: int) -> str:
    """Bucket successful values into `bins` buckets and draw an SVG bar chart."""
    if not values:
        return _empty_svg(width, height, "No successful samples to histogram")

    lo, hi = min(values), max(values)
    if lo == hi:
        lo, hi = lo - 0.5, hi + 0.5
    bin_width = (hi - lo) / bins

    counts = [0] * bins
    for value in values:
        idx = min(int((value - lo) / bin_width), bins - 1)
        counts[idx] += 1
    max_count = max(counts)

    margin = 40
    plot_w = width - 2 * margin
    plot_h = height - 2 * margin
    bar_w = plot_w / bins

    parts: List[str] = []
    for i, count in enumerate(counts):
        bar_h = (count / max_count) * plot_h if max_count else 0.0
        x = margin + i * bar_w
        y = margin + (plot_h - bar_h)
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(bar_w - 2, 0):.1f}" '
            f'height="{bar_h:.1f}" class="bar" />'
        )
        if count:
            parts.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{y - 4:.1f}" class="bar-label" '
                f'text-anchor="middle">{count}</text>'
            )

    parts.append(
        f'<line x1="{margin}" y1="{margin + plot_h}" x2="{margin + plot_w}" '
        f'y2="{margin + plot_h}" class="axis" />'
    )
    parts.append(
        f'<text x="{margin}" y="{height - 8}" class="axis-label">{lo:.4f}</text>'
    )
    parts.append(
        f'<text x="{margin + plot_w}" y="{height - 8}" class="axis-label" '
        f'text-anchor="end">{hi:.4f}</text>'
    )

    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="Histogram of successful measurement values">'
        f'{"".join(parts)}</svg>'
    )


def _build_time_series_svg(
    raw_results: Sequence[Dict[str, Any]],
    outlier_indices: Set[int],
    width: int,
    height: int,
) -> str:
    """Draw sample index (x) vs. value (y); mark outliers and failures distinctly."""
    if not raw_results:
        return _empty_svg(width, height, "No samples")

    margin = 40
    plot_w = width - 2 * margin
    plot_h = height - 2 * margin
    n = len(raw_results)
    x_step = plot_w / max(n - 1, 1)

    def x_for(i: int) -> float:
        return margin + i * x_step

    successful = [(i, r["value"]) for i, r in enumerate(raw_results) if r["error"] is None]

    parts: List[str] = [
        f'<line x1="{margin}" y1="{margin + plot_h}" x2="{margin + plot_w}" '
        f'y2="{margin + plot_h}" class="axis" />'
    ]

    if successful:
        values = [v for _, v in successful]
        lo, hi = min(values), max(values)
        if lo == hi:
            lo, hi = lo - 0.5, hi + 0.5

        def y_for(v: float) -> float:
            return margin + plot_h - ((v - lo) / (hi - lo)) * plot_h

        points = " ".join(f"{x_for(i):.1f},{y_for(v):.1f}" for i, v in successful)
        parts.append(f'<polyline points="{points}" class="series-line" fill="none" />')
        for i, v in successful:
            css_class = "point-outlier" if i in outlier_indices else "point"
            parts.append(
                f'<circle cx="{x_for(i):.1f}" cy="{y_for(v):.1f}" r="3" class="{css_class}" />'
            )

    for i, sample in enumerate(raw_results):
        if sample["error"] is not None:
            parts.append(
                f'<circle cx="{x_for(i):.1f}" cy="{margin + plot_h:.1f}" r="4" '
                f'class="point-failure" />'
            )

    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="Time series of measurement values by sample index">'
        f'{"".join(parts)}</svg>'
    )


def _build_html_document(
    run_id: str,
    metadata: Dict[str, Any],
    stats_table: str,
    histogram_svg: str,
    time_series_svg: str,
) -> str:
    """Assemble the full self-contained HTML page (inline CSS, no external assets)."""
    device = html_lib.escape(str(metadata.get("device", "")))
    duration = metadata.get("duration_seconds")
    jitter = metadata.get("jitter", {})

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Ammeter QA report - {html_lib.escape(run_id)}</title>
<style>
  body {{ font-family: -apple-system, Helvetica, Arial, sans-serif; margin: 2rem; color: #1a1a1a; background: #fafafa; }}
  h1 {{ font-size: 1.4rem; }}
  h2 {{ font-size: 1.1rem; margin-top: 2rem; }}
  table.stats {{ border-collapse: collapse; }}
  table.stats th, table.stats td {{ border: 1px solid #ccc; padding: 0.35rem 0.75rem; text-align: left; }}
  table.stats th {{ background: #eee; font-weight: 600; }}
  svg {{ background: #fff; border: 1px solid #ddd; }}
  .bar {{ fill: #4c78a8; }}
  .bar-label {{ font-size: 10px; fill: #333; }}
  .axis {{ stroke: #999; stroke-width: 1; }}
  .axis-label {{ font-size: 10px; fill: #555; }}
  .series-line {{ stroke: #4c78a8; stroke-width: 1.5; }}
  .point {{ fill: #4c78a8; }}
  .point-outlier {{ fill: #e45756; }}
  .point-failure {{ fill: #e45756; opacity: 0.6; }}
  .empty-message {{ font-size: 13px; fill: #888; }}
  .meta {{ color: #555; font-size: 0.9rem; }}
</style>
</head>
<body>
<h1>Ammeter QA report</h1>
<p class="meta">
  Run ID: <code>{html_lib.escape(run_id)}</code><br>
  Device: {device}<br>
  Duration: {_fmt(duration, 2)}s<br>
  Jitter mean/max: {_fmt(jitter.get("mean_seconds"), 5)}s / {_fmt(jitter.get("max_seconds"), 5)}s
</p>

<h2>Statistics</h2>
{stats_table}

<h2>Value distribution</h2>
{histogram_svg}

<h2>Time series</h2>
{time_series_svg}
</body>
</html>
"""


def generate_html_report(
    run_document: Dict[str, Any],
    output_dir: Path,
    histogram_bins: int = 10,
    svg_width: int = 640,
    svg_height: int = 280,
) -> Path:
    """Render a saved run document to a self-contained HTML report.

    Args:
        run_document: A run document as produced by
            src.testing.store.build_run_document (or returned by load_run):
            must contain "run_id", "metadata", "raw_results", and
            "analyzed_results".
        output_dir: Directory the report is written into; created if it
            doesn't exist.
        histogram_bins: Number of buckets for the value histogram.
        svg_width: Width in pixels of each generated SVG chart.
        svg_height: Height in pixels of each generated SVG chart.

    Returns:
        Path to the written "{run_id}.html" file.

    Raises:
        OSError: If output_dir can't be created or the file can't be written.
    """
    run_id = run_document["run_id"]
    metadata = run_document["metadata"]
    raw_results = run_document["raw_results"]
    analyzed = run_document["analyzed_results"]

    successful_values = [r["value"] for r in raw_results if r["error"] is None]
    outlier_indices = set(analyzed["outliers"]["indices"])

    stats_table = _build_stats_table(analyzed)
    histogram_svg = _build_histogram_svg(successful_values, histogram_bins, svg_width, svg_height)
    time_series_svg = _build_time_series_svg(raw_results, outlier_indices, svg_width, svg_height)

    document = _build_html_document(run_id, metadata, stats_table, histogram_svg, time_series_svg)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{run_id}.html"
    output_path.write_text(document, encoding="utf-8")
    return output_path
