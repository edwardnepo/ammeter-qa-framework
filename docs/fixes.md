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
