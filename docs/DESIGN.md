# Design Decisions and Tradeoffs

## Why the live smoke test matters: a bug mocked tests couldn't see

After building the core testing layer (`sampler.py`, `analyzer.py`,
`store.py`, `test_framework.py`, `cli.py`) with a fully passing pytest
suite, running it against the three *live* emulators immediately failed
100% of samples with timeouts on every device. The cause:
`AmmeterTestFramework.run_test()` used the driver as a context manager
around the entire sampling loop (`with driver: run_sampling(driver,
plan)`), intending `connect()`/`close()` as a fail-fast reachability
preflight. But `Ammeters/base_ammeter.py`'s server is single-threaded and
services exactly one connection at a time, blocking indefinitely in
`conn.recv()` with no server-side timeout. Holding the preflight
connection open for the whole ~10-second sampling run left the server
permanently stuck waiting on that idle connection's `recv()`, so it never
returned to `accept()` to service any of `run_sampling`'s own connection
attempts — every one of them timed out waiting for a reply that could
never arrive. The fix was to call `driver.connect()` then `driver.close()`
back-to-back before sampling starts, not wrap the loop in them.

No mocked test could have caught this: `tests/testing/test_test_framework.py`
and `tests/drivers/test_base.py` both replace the socket layer with
`unittest.mock` objects, where `connect()`, `close()`, and `measure()` are
independent, instantaneous calls with no shared state and no notion of a
single-threaded server that can only handle one real connection at a
time. The bug lived entirely in the *interaction* between this code's
connection-lifecycle choice and the specific concurrency model of the
supplied emulator's TCP server — an environment-specific timing and
concurrency property that, by construction, a test double can't model
because it doesn't model the server at all. This is why every layer of
this framework is verified with a manual run against the real, running
emulators in addition to its pytest suite: unit tests with mocked I/O
prove the code does what it was told to do, but only a live integration
run proves what it does actually works against the real protocol.

## Fault injection: composition over inheritance, and a deliberately silent fault

`src/faults/injector.py`'s `FaultInjectingDriver` wraps an `AmmeterDriver`
by **composition**, not inheritance, and is not registered as a driver
type in `config.yaml` — `src/drivers/registry.py`'s `build_driver()`
requires the resolved class to be an `AmmeterDriver` subclass, so a fault
injector that *is* one would need to fake being a real vendor driver.
Composition keeps it what it actually is: a runtime wrapper applied around
a driver the registry already built, via `AmmeterTestFramework.run_test()`'s
new optional `driver_wrapper` hook. That hook defaults to `None` so every
existing caller and test is unaffected — the only new coupling is the CLI's
`--fault-injection` flag choosing to pass one.

Of the four injectable faults, three (`timeout`, `disconnect`,
`corrupted_response`) are **transport-level**: they synthesize a
`MeasurementSample` with `error` set, exactly like a real
`AmmeterDriver.measure()` failure, so they're fully visible in
`failure_count`/`failure_rate_percent`. The fourth, `negative_value`, is
different on purpose: it takes a genuine reading and flips its sign,
returning a **structurally successful sample carrying a physically
impossible current**. `error` is deliberately left `None`. This is a
domain-level fault, not a transport-level one — the analyzer has no notion
of "a current can't be negative," so this fault is invisible to every
failure-counting metric and only shows up by pulling `mean`/`min` into
implausible territory.

**failure_rate_percent measures communication failures only; physical
implausibility (e.g. negative current) is not flagged as a failure but is
visible via IQR outlier detection and min/max — a documented scope
boundary, not a gap.** In the live run below, both injected
`negative_value` samples were in fact caught by IQR outlier detection
(their indices appear in `analyzed_results.outliers.indices`) — but that's
`analyzer.py`'s general-purpose statistical-distance check doing
incidental double duty, not a domain-validity rule; a negative reading
close enough to zero wouldn't necessarily clear the IQR threshold. The
only mechanism that's guaranteed to surface it is a human (or the HTML
report/`compare` output) actually looking at `min`.

A live run against all three real emulators with `fault_rate=0.25`
confirmed the failure/injection split: each device reported
`injected_faults=8` but only 6 counted as `failures` — the other 2 were
negative-value corruptions that passed as "successes." Comparing that run
against a clean baseline with the new `compare` command made the effect
concrete: `min` went from `0.0044` to `-0.0552` while
`failure_rate_percent` only moved from `0%` to `30%`, understating how
much of the run's data was actually untrustworthy. That gap is the point:
it demonstrates why "zero reported failures" isn't the same as "clean
data," and is a concrete argument for a future extension (domain sanity
bounds in the analyzer, e.g. rejecting or flagging negative currents) that
this submission deliberately doesn't implement, to avoid scope creep
beyond what was asked.

## HTML report: hand-rolled SVG instead of a charting library

`src/reporting/html_report.py` builds its histogram and time-series charts
as inline `<svg>` via plain string templating — no matplotlib, no other
third-party dependency. `reporting/` is the one place the project's rules
allow an optional dependency to live (isolated, degrading gracefully when
absent), but this report needed nothing beyond stdlib to satisfy the
actual requirement: two simple charts and a stats table from data already
shaped as plain floats. Reaching for matplotlib would have added a real
dependency (with its own README/requirements.txt disclosure burden) for
capability this module doesn't use — no interactivity, no complex plot
types, just bars and a polyline. The tradeoff is more code in this file
(manual axis scaling, bucketing, coordinate math) in exchange for a report
that's a single self-contained HTML file with zero runtime dependencies to
render, and that degrades to a "no successful samples" placeholder instead
of crashing when a fault-injection run legitimately produces zero
successes.
