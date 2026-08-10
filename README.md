# Ammeter Emulators

This project provides emulators for different types of ammeters: Greenlee, ENTES, and CIRCUTOR. Each ammeter emulator runs on a separate thread and can respond to current measurement requests.

## Project Structure

- `main.py`: Starts the three ammeter emulators and requests one
  measurement from each (the original "before you start" script).
- `Ammeters/`
  - `Circutor_Ammeter.py`, `Entes_Ammeter.py`, `Greenlee_Ammeter.py`:
    the three ammeter emulators (untouched hardware simulators).
  - `base_ammeter.py`: shared TCP server base class for the emulators.
  - `client.py`: minimal client used by the emulators' own tests.
- `config/`
  - `config.yaml`: single source of truth for ports, commands, sampling,
    analysis, result storage, and fault injection — see "Adding a fourth
    ammeter" below for how drivers plug into it.
- `examples/`
  - `run_tests.py`: legacy example script — **do not use it** (per the
    project spec); the QA framework's own CLI (below) is the supported
    way to run tests.
- `src/`: the QA testing framework proper.
  - `drivers/`: `base.py` (the `AmmeterDriver` ABC and TCP protocol),
    one thin subclass per vendor (`greenlee.py`, `entes.py`,
    `circutor.py`), and `registry.py` (resolves config's `driver` key to
    a class via `importlib`, with zero per-vendor branching).
  - `testing/`: `sampler.py` (absolute-deadline sampling), `analyzer.py`
    (mean/median/stdev/CV/IQR outliers), `store.py` (run persistence,
    JSON + index), `test_framework.py` (`AmmeterTestFramework`, the
    orchestration entry point `src/cli.py` calls).
  - `faults/injector.py`: `FaultInjectingDriver`, a composition-based
    wrapper that injects timeouts/disconnects/corrupted or
    negative-value readings for the `--fault-injection` flag.
  - `reporting/html_report.py`: renders a saved run into a
    self-contained HTML report (see "HTML reports" below).
  - `utils/config.py`: loads and validates `config.yaml`.
  - `utils/Utils.py`: shared helpers used by the emulator layer
    (`generate_random_float`).
  - `cli.py`: the `run` / `list` / `show` / `compare` commands
    documented below.
- `tests/`: pytest suite, mirroring the `src/` layout.
- `results/`: saved run JSON documents, `index.json`, and generated HTML
  reports (see "Sample results" below).
- `docs/`: `investigation.md` (original bug audit), `fixes.md` (every
  fix applied and why), `DESIGN.md` (design decisions and tradeoffs).

## Usage

# Ammeter Emulators

## Greenlee Ammeter

- **Port**: 5000
- **Command**: `MEASURE_GREENLEE -get_measurement`
- **Measurement Logic**: Calculates current using voltage (1V - 10V) and (0.1Ω - 100Ω).
- **Measurement method** : Ohm's Law: I = V / R

## ENTES Ammeter

- **Port**: 5001
- **Command**: `MEASURE_ENTES -get_data`
- **Measurement Logic**: Calculates current using magnetic field strength (0.01T - 0.1T) and calibration factor (500 - 2000).
- **Measurement method** : Hall Effect: I = B * K

## CIRCUTOR Ammeter

- **Port**: 5002
- **Command**: `MEASURE_CIRCUTOR -get_measurement -current`
- **Measurement Logic**: Calculates current using voltage values (0.1V - 1.0V) over a number of samples and a random time step (0.001s - 0.01s).
- **Measurement method** : Rogowski Coil Integration: I = ∫V dt

To start the ammeter emulators and request current measurements, run the `main.py` script:
```sh
python main.py
```

## Testing framework CLI

With the emulators running (`python main.py`, or any process that starts
them and stays up), the QA framework's CLI runs sampling tests against
them and manages the results:

```sh
# Run a test against one ammeter, or all of them
python -m src.cli run greenlee
python -m src.cli run all

# List saved runs
python -m src.cli list
python -m src.cli list --device circutor --limit 5

# Show one saved run's full detail
python -m src.cli show 20260810-125503-circutor-22a112

# Compare two saved runs (mean/median/stdev/min/max/CV/failure-rate deltas)
python -m src.cli compare 20260810-125503-circutor-22a112 20260810-133247-circutor-4a900c
```

(Those two run IDs are real, checked-in examples under `results/runs/` —
a clean baseline vs. a `--fault-injection` run against the same CIRCUTOR
device; see "Sample results" below.)

### Fault injection

`run` accepts `--fault-injection`, which wraps each device's driver in a
`FaultInjectingDriver` (`src/faults/injector.py`) that injects timeouts,
disconnects, corrupted responses, and negative-value readings at a rate
controlled by config.yaml's `fault_injection` section (disabled by
default; seeded for reproducibility):

```sh
python -m src.cli run all --fault-injection
```

The printed summary line adds `injected_faults=N`. This proves the
sampler/analyzer/store pipeline survives bad data instead of crashing —
see `docs/DESIGN.md` for why one of the four fault types is deliberately
invisible to the failure count.

### HTML reports

`src/reporting/html_report.py` renders a saved run document into a
self-contained HTML file (stats table plus hand-rolled SVG histogram and
time-series charts, no third-party dependency):

```python
from pathlib import Path
from src.testing.store import load_run
from src.reporting.html_report import generate_html_report

run = load_run("<run_id>", {"results_dir": "results", "runs_subdir": "runs"})
path = generate_html_report(run, Path("results/reports"))
```

## Adding a fourth ammeter

Adding a new vendor takes exactly two steps — no existing code is edited:

1. **Write one driver file** under `src/drivers/`, subclassing
   `AmmeterDriver` (`src/drivers/base.py`) and setting `DEFAULT_COMMAND`
   (and optionally `DEFAULT_UNIT`) as a fallback, following the pattern in
   `src/drivers/greenlee.py`:

   ```python
   # src/drivers/newvendor.py
   from src.drivers.base import AmmeterDriver

   class NewVendorDriver(AmmeterDriver):
       DEFAULT_COMMAND = b"MEASURE_NEWVENDOR -get_measurement"
   ```

2. **Add one entry** under `ammeters:` in `config/config.yaml`, pointing
   `driver` at that class's dotted import path:

   ```yaml
   ammeters:
     newvendor:
       driver: "src.drivers.newvendor.NewVendorDriver"
       host: "localhost"
       port: 5003
       command: "MEASURE_NEWVENDOR -get_measurement"
       timeout_seconds: 2.0
       retries: 3
       retry_backoff_seconds: 0.5
   ```

`src/drivers/registry.py::build_driver` resolves `driver` via
`importlib` at run time — nothing outside these two files knows the
vendor's name. `python -m src.cli run newvendor` (or `run all`) picks it
up immediately, with no changes to `cli.py`, `registry.py`, or any other
driver.

## Sample results

`results/` has six checked-in real runs from two live sessions against
the actual emulators (not synthetic/test fixtures):

- `20260810-125503-circutor-22a112`, `20260810-125512-entes-0d2ed7`,
  `20260810-125522-greenlee-60318c` — clean baseline, one per device,
  0% failures.
- `20260810-133247-circutor-4a900c`, `20260810-133300-entes-6862f1`,
  `20260810-133313-greenlee-e8ebb1` — the same three devices with
  `--fault-injection` enabled (`fault_rate=0.25`); see `docs/DESIGN.md`
  for why `failure_rate_percent` (30%) understates how much of the data
  is actually suspect once `negative_value` faults are counted.
- `results/reports/20260810-133247-circutor-4a900c.html` — a generated
  HTML report for the CIRCUTOR fault-injection run (see "HTML reports"
  above for how to generate one for any other run).

`python -m src.cli show <run_id>` or `compare <run_id_a> <run_id_b>` (see
above) work against any of these out of the box.

## Installed Libraries

Dependencies live in `requirements.txt`; install with
`pip install -r requirements.txt`. This list matches `requirements.txt`
exactly and is kept minimal on purpose (see `CLAUDE.md`'s "core is
stdlib" rule) — everything else the framework uses (`socket`,
`statistics`, `json`, `csv`, `pathlib`, `argparse`, `dataclasses`,
`threading`, `logging`, `time`) is standard library.

- `pyyaml` — parses `config/config.yaml` (`src/utils/config.py`,
  `src/cli.py`).
- `pytest` — test framework used for the project's automated test suite.