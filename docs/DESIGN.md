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
