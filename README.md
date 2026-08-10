# Ammeter Emulators

This project provides emulators for different types of ammeters: Greenlee, ENTES, and CIRCUTOR. Each ammeter emulator runs on a separate thread and can respond to current measurement requests.

## Project Structure

- `Ammeters/`
  - `main.py`: Main script to start the ammeter emulators and request current measurements.
  - `Circutor_Ammeter.py`: Emulator for the CIRCUTOR ammeter.
  - `Entes_Ammeter.py`: Emulator for the ENTES ammeter.
  - `Greenlee_Ammeter.py`: Emulator for the Greenlee ammeter.
  - `base_ammeter.py`: Base class for all ammeter emulators.
  - `client.py`: Client to request current measurements from the ammeter emulators.
- `config/`
  - `config.yaml`: Configuration file for the ammeter emulators.
- `examples/`
  - `run_test.py`: super lyze example for run test **don't use it**.
- `src/`
  - `testing/`
    - `AmmeterTester.py`: Class to test the ammeter emulators.
  - `utils/`
    - `config.py`: Configuration settings.
    - `logger.py`: Logging setup.
    - `Utils.py`: Utility functions, including `generate_random_float`.

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
python -m src.cli show <run_id>

# Compare two saved runs (mean/median/stdev/min/max/CV/failure-rate deltas)
python -m src.cli compare <run_id_a> <run_id_b>
```

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