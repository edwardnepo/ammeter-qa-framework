# Fixes

Every bug found in the supplied code, documented as it was fixed. See
`docs/investigation.md` for the original read-only audit these entries
resolve.

## 1. `main.py` bound the wrong ports

**Symptom:** Running `main.py` and then querying the emulators using the
ports documented in `README.md` / `config.yaml` (5000/5001/5002) would
never connect — the servers weren't listening there.

**Root cause:** `main.py:11,15,19` bound Greenlee/ENTES/CIRCUTOR to
5001/5002/5003. Three independent sources (`README.md`, `config.yaml`,
and the project spec) agree on 5000/5001/5002; `main.py` was the outlier.

**Fix:** Changed the three `AmmeterEmulatorBase` subclass instantiations
in `main.py` to ports 5000/5001/5002.

**Why:** With three sources agreeing and only `main.py` disagreeing,
`main.py` is the bug, not the documentation. Fixing it here (rather than
changing the docs to match) keeps the ports the framework will read from
`config.yaml` consistent with what's already documented.

## 2. `main.py` client calls were commented out and wrong

**Symptom:** The spec requires `main.py` to "make the main.py script work
and return data from the ammeters," but the client calls were commented
out. Even uncommented as-is they would never have worked.

**Root cause:** `main.py:33-35` used bare commands
(`b'MEASURE_GREENLEE'`, `b'MEASURE_ENTES'`, `b'MEASURE_CIRCUTOR'`).
`Ammeters/base_ammeter.py:27` replies only on byte-for-byte equality with
`get_current_command`, which requires the full suffix on every emulator
(`-get_measurement`, `-get_data`, `-get_measurement -current`). A
mismatch is silently dropped (no error reply), so the bare commands would
have produced "No data received." with no indication why.

**Fix:** Uncommented the three `request_current_from_ammeter` calls in
`main.py`, using each emulator's exact command bytes (as defined in
`Ammeters/{Greenlee,Entes,Circutor}_Ammeter.py`), and updated the port
numbers to match the fix above.

**Why:** `main.py` is the entry point, not one of the `Ammeters/*.py`
driver classes the "don't touch emulator files" rule protects — fixing
its client calls is explicitly in scope per the spec.
