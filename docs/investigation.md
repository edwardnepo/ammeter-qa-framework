# Investigation: Supplied Ammeter Codebase

Read-only analysis of the code as delivered, before any implementation work
started. Covers the file map, the exact wire protocol per emulator, every
bug found (with line numbers), and the open questions that need a decision
before real implementation planning begins.

## 1. File map

### Ammeters/base_ammeter.py
`AmmeterEmulatorBase` — abstract base class. Owns the TCP server loop:
bind, listen, accept one connection at a time. Subclasses must provide
`get_current_command` (bytes property) and `measure_current()` (float).

### Ammeters/Greenlee_Ammeter.py
`GreenleeAmmeter(AmmeterEmulatorBase)`. Ohm's law model: `I = V/R`.

### Ammeters/Entes_Ammeter.py
`EntesAmmeter(AmmeterEmulatorBase)`. Hall-effect model: `I = B·K`.

### Ammeters/Circutor_Ammeter.py
`CircutorAmmeter(AmmeterEmulatorBase)`. Rogowski-coil integration model:
`I = Σ(Vᵢ·dt)` over 10 samples.

### Ammeters/client.py
`request_current_from_ammeter(port, command)` — opens a single socket,
sends `command`, reads up to 1024 bytes, prints the decoded reply or
"No data received."

### main.py
Entry point. Starts the three emulators as daemon threads, sleeps 5
seconds, then (commented out) would query each one over the client.

### config/config.yaml
Config skeleton for sampling, ammeters, analysis, and result management.
Sampling values are literal YAML `NULL`; the entire `ammeters:` block is
commented out.

### src/utils/config.py
`load_config(path) -> Dict` — thin `yaml.safe_load` wrapper, no error
handling.

### src/utils/logger.py
`TestLogger` — intends to log to `results/logs/<timestamp>_<name>.log`,
but never actually attaches a handler (see bugs below).

### src/utils/Utils.py
`generate_random_float(min, max)` — thin `random.uniform` wrapper, used
by all three emulators.

### src/testing/test_framework.py
`AmmeterTestFramework` — stub. Loads config in `__init__`; `run_test()`
is an unimplemented `pass`.

### examples/run_tests.py
Documented-broken sample. README explicitly says "don't use it."

Note: there is no `__init__.py` anywhere under `src/` — `src`, `src/testing`,
and `src/utils` are not yet formal Python packages.

## 2. Exact protocol per emulator

The server (`base_ammeter.py:22-30`) accepts one connection, reads up to
1024 bytes, and replies only if the bytes are byte-for-byte equal to
`get_current_command`. On any mismatch it sends nothing and closes the
connection. The client's `recv()` then returns `b''` (EOF, not a hang),
which `client.py` reports as "No data received." There is no
length-prefix or delimiter framing — the reply is just
`str(current_value).encode('utf-8')`, a plain ASCII float with no unit
and no error envelope.

### Greenlee
- Port bound by `main.py`: 5001 (`main.py:11`)
- Port documented in README / config.yaml: 5000
- Exact command bytes: `b'MEASURE_GREENLEE -get_measurement'`
- README command text: matches the source

### ENTES
- Port bound by `main.py`: 5002 (`main.py:15`)
- Port documented in README / config.yaml: 5001
- Exact command bytes: `b'MEASURE_ENTES -get_data'`
- README command text: matches the source

### CIRCUTOR
- Port bound by `main.py`: 5003 (`main.py:19`)
- Port documented in README / config.yaml: 5002
- Exact command bytes: `b'MEASURE_CIRCUTOR -get_measurement -current'`
- README command text: missing the `-current` flag (README.md:47)

## 3. Bugs found

### main.py
- Lines 11, 15, 19 — binds Greenlee/ENTES/CIRCUTOR to 5001/5002/5003,
  contradicting README.md (lines 32, 39, 46) and config.yaml's commented
  port block (lines 9, 12, 15), which all say 5000/5001/5002.
- Lines 33-35 — the commented-out client calls use bare commands
  (`b'MEASURE_GREENLEE'`, etc.) missing the required suffixes
  (`-get_measurement`, `-get_data`, `-get_measurement -current`). Even
  uncommented as-is, they would never match the server's exact-equality
  check.
- Line 32 — `time.sleep(5)` is the only readiness mechanism for the
  server threads. The comment above it admits this is fragile ("if you
  have problem restarting the servers... try increasing sleep time").
  There is no handshake or ready signal.
- No `SO_REUSEADDR` is ever set (see `base_ammeter.py:18-19`) — rerunning
  `main.py` shortly after a previous run can raise
  `OSError: [Errno 48] Address already in use`.

### Ammeters/base_ammeter.py
- Lines 22-30 — no exception handling around `conn.recv`/`conn.sendall`
  (e.g. `ConnectionResetError`); a bad client can crash the accept loop
  for that emulator.
- Line 27 — a non-matching command is silently dropped with no error
  reply, so protocol mismatches are invisible from the client side unless
  you already know to check for an empty response.
- No shutdown path exists — `start_server()` loops forever; daemon
  threads are simply killed at process exit.

### Ammeters/Circutor_Ammeter.py
- Line 9 — the actual command is
  `MEASURE_CIRCUTOR -get_measurement -current`, but README.md line 47
  documents it without `-current`. A client built strictly from the
  README would be silently rejected.

### README.md
- Lines 32, 39, 46 — ports 5000/5001/5002 don't match `main.py`'s actual
  5001/5002/5003.
- Line 47 — Circutor command is missing the `-current` flag.

### config/config.yaml
- Lines 1-6 — sampling values are literally the YAML `NULL`, not usable
  placeholders.
- Lines 8-16 — the entire `ammeters:` mapping is commented out; as
  written, `yaml.safe_load` will give `config['ammeters'] == None`. The
  commented-out block also still encodes the wrong ports (5000/5001/5002).
- Lines 18-25 — `analysis.statistical_metrics`,
  `analysis.visualization.plot_types`, and `result_management` are empty
  keys — the schema exists in name only, with no defined shape.

### src/utils/config.py
- No error handling around the file open or `yaml.safe_load` call — a
  missing file or malformed YAML propagates a raw `FileNotFoundError` or
  `yaml.YAMLError`.
- Docstring is in Hebrew, inconsistent with the rest of the (English)
  codebase.

### src/utils/logger.py
- Lines 10-26 (`_setup_logger`) — creates `results/logs/` and computes a
  timestamped log file path, but never attaches a `logging.FileHandler`
  (or any handler) to the returned logger, and never sets a level or
  formatter. Calls to `.info()`, `.debug()`, etc. are effectively silent,
  and nothing is ever written to the directory the code just created.
- Comments throughout are in Hebrew.

### src/testing/test_framework.py
- Line 3 — `from ..utils.config import load_config` is a relative import
  requiring `src`, `src.testing`, and `src.utils` to be real packages,
  but there is no `__init__.py` anywhere under `src/`. Importing or
  running this module directly (not as a submodule of an installed
  package) raises `ImportError: attempted relative import with no known
  parent package`.
- Line 10 — `def run_test(self, ammeter_type: str) -> Dict:` references
  `Dict` from `typing`, which is never imported. Since there is no
  `from __future__ import annotations`, the annotation is evaluated
  eagerly and raises `NameError` at class-definition time.
- Line 11 — the method body is `pass`; it never touches `ammeter_type` or
  `self.config`, and no socket connection is ever made.

### examples/run_tests.py
- Line 13 — `framework.run_test()` is called with zero arguments against
  a signature that requires `ammeter_type` (`test_framework.py:10`),
  raising `TypeError` — on top of the import already failing. README.md
  line 17 already flags this file as broken and not to be used.
- Comments throughout are in Hebrew.

### Emulator math (Greenlee, ENTES)
No correctness bugs found — the logic matches the documented formulas.

## 4. Open questions

### Port ground truth
`main.py` uses 5001/5002/5003; README, config.yaml, and the project
instructions all say 5000/5001/5002. Which side is authoritative — shift
`main.py` to match the docs, or fix the docs to match `main.py`?

### Is main.py in scope as an "emulator file"?
The rule against touching emulator files unless fixing a real bug names
the `Ammeters/*.py` driver classes. `main.py` isn't one of those, but it
owns the port binding and the commented-out client calls. Does fixing the
port mismatch or correcting the client calls in `main.py` count as
in-scope? Does "original main.py still runs" mean unchanged, or just
still runs without crashing?

### Circutor command mismatch
Fix the README to include `-current` (a documentation bug), or simplify
the emulator's command to match the README (an emulator bug)? These are
different fixes with very different blast radius.

### TestLogger
Fix `_setup_logger` in place to attach a real `FileHandler`, or treat
`src/utils/logger.py` as superseded by a new logging setup in whatever
architecture gets built? It isn't mentioned explicitly in the proposed
target layout.

### Where does the new package live?
The spec says to use the existing infrastructure, and `src/testing/` and
`src/utils/` already contain real, if broken, content —
`AmmeterTestFramework`, `load_config`, `generate_random_float` are all
things new code could extend rather than replace. Should the new
architecture be built inside `src/` by fixing and extending what's
there, or as a new package alongside it, with `src/` effectively
retired?

### config.yaml ammeter schema
Once filled in, should it enumerate exactly `greenlee`, `entes`, and
`circutor` to match the three existing driver classes one-to-one, or
should each entry carry a `driver`/`module` key from the start, so that
adding a fourth ammeter is provable against the config schema itself and
not just the driver registry?

### pytest in requirements.txt
It's named as an allowed dependency in the project instructions but
isn't currently listed in `requirements.txt` or installed in `.venv`.
Add it now and note it in the README per the spec's "list installed
libraries" requirement, or defer until the test-writing layer actually
starts?
