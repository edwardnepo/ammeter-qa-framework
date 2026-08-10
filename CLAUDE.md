# Ammeter QA Framework — Project Instructions

## Context
This is a take-home assignment for a QA / embedded-systems engineering role.
It will be reviewed by a panel of senior engineers. The graded criteria are:
code quality and structure, framework flexibility, comprehensive error
handling, clear result reporting, and potential for extension and reuse.

The repository ships with three ammeter emulators (Greenlee port 5000,
ENTES port 5001, CIRCUTOR port 5002) that speak plain-text commands over TCP.
My job is to build the testing framework around them — not to rewrite them.

## Hard rules

- **Core is stdlib**, plus only the dependencies the supplied project
  already requires (e.g. a YAML parser for `config/config.yaml`, and
  `pytest` for tests). Prefer `socket`, `statistics`, `json`, `csv`,
  `pathlib`, `argparse`, `dataclasses`, `threading`, `logging`, `time`.
  Any further optional dependency lives in `reporting/` and must degrade
  gracefully when absent.
- **Never add a dependency without asking me first.** Every installed
  library must be listed in the README, as the spec requires.
- **No bare `except:`.** Catch specific exceptions, log with context, and
  re-raise or return a typed error result. Never swallow silently.
- **Type hints on every public function**, plus a docstring with
  Args / Returns / Raises.
- **Cross-platform.** `pathlib` everywhere, no shell commands, no
  OS-specific paths or assumptions.
- **Config-driven.** No magic numbers, ports, timeouts, or device names
  hardcoded in logic. Everything comes from `config/config.yaml`.
- **Don't touch the emulator files** unless fixing a real bug — and if you
  fix one, document it in `docs/fixes.md` in the same commit.
- **Never modify `examples/run_test.py`.** The spec says not to use it.

## Working style

- Default to **plan mode** for anything larger than a single function.
  Show me the plan, wait for approval, then implement.
- **One layer at a time.** Do not scaffold the whole project in one pass.
- Write **pytest tests for each layer before moving to the next**.
- **Small commits** with conventional messages (`fix:`, `feat:`, `test:`,
  `docs:`). One logical change per commit.
- Explain design tradeoffs in chat, not only in code comments. If there
  was a real choice, I need to be able to defend it in an interview.
- If a requirement is ambiguous, ask me — do not silently pick an
  interpretation.

## Target architecture (RESOLVED after investigation — see docs/investigation.md)

Build inside the existing `src/` tree, extending what's there rather than
creating a parallel package. The spec explicitly says to use the existing
infrastructure, and `src/testing/test_framework.py`, `src/utils/config.py`,
and `src/utils/Utils.py` already contain real (if broken) logic to fix and
extend. Add `src/__init__.py`, `src/testing/__init__.py`,
`src/utils/__init__.py` so relative imports actually work.

```
src/
  drivers/
    base.py        AmmeterDriver ABC: connect / measure / close
    greenlee.py    entes.py    circutor.py
    registry.py    name -> class mapping, driven by config.yaml's
                    per-ammeter `driver`/`module` key so a 4th ammeter
                    is provable from the config schema itself
  testing/
    test_framework.py   fixed + extended, not replaced
    sampler.py      count / duration / rate, absolute-deadline scheduling
    analyzer.py      mean, median, stdev, min, max, CV, IQR outliers
    store.py         run_id, metadata, JSON persistence, run index
  utils/
    config.py        fixed: real error handling added
    logger.py         fixed: FileHandler actually attached
    Utils.py
  reporting/
    console.py    html.py    (optional deps isolated here)
  faults/
    injector.py    FaultInjectingDriver wrapper
  cli.py           run / list / show / compare
config/config.yaml
tests/
docs/investigation.md   docs/fixes.md    docs/DESIGN.md
results/
```

**Extension test:** adding a fourth ammeter model must require exactly one
new driver file plus one entry in `config.yaml` — zero edits to existing
code. If a change breaks that property, flag it.

## Fix decisions already made (do not re-litigate)

- Ports: `main.py` is wrong (binds 5001/5002/5003). Fix `main.py` to match
  README/config.yaml (5000/5001/5002) — three sources agree, one doesn't.
- `main.py` client calls: in scope to fix. The spec explicitly requires
  "make the main.py script work and return data from the ammeters." The
  "don't touch emulator files" rule applies to `Ammeters/*.py` driver
  classes, not the entry point.
- Circutor `-current` flag: fix the README (documentation bug), not the
  emulator. The emulator represents the "hardware" and stays untouched.
  Missing this flag anywhere else (default config, examples) is a bug.
- `TestLogger`: fix the existing bug (attach a real `FileHandler`) and
  document it in fixes.md. Don't over-invest — the framework's real
  logging setup is whatever gets built in the new architecture.
- Add `pytest` to `requirements.txt` now; list it in the README's
  installed-libraries section immediately, not deferred.

## Timing requirements

Sampling must use absolute deadlines, not cumulative sleeps:

```python
next_t = start + i / rate
time.sleep(max(0.0, next_t - time.perf_counter()))
```

Measure and report actual jitter in the run metadata. Naive
`time.sleep(1/rate)` accumulates drift and is not acceptable here.

## Known conceptual trap

The three emulators generate independent random parameters, so they have no
shared ground-truth current. **Accuracy in the metrological sense cannot be
measured here.** What the framework can measure is precision and
repeatability: spread, coefficient of variation, and stability over time.
Optionally, cross-check each device against its own theoretical formula
(I = V/R, I = B·K) as a sanity check. This reasoning must appear explicitly
in `docs/DESIGN.md` — it is the strongest point in the submission.

## Deliverables checklist

- [ ] Original `main.py` still runs
- [ ] `docs/fixes.md` — every bug found in the supplied code, documented
- [ ] `docs/DESIGN.md` — design decisions and tradeoffs
- [ ] `README.md` — install, run, CLI examples, "how to add a 4th ammeter"
- [ ] `requirements.txt` + list of installed libraries stated in the README
- [ ] `results/` — 2-3 saved sample runs
- [ ] pytest suite passing
- [ ] Clean commit history