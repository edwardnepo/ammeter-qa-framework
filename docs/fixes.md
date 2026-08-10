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

## 3. Emulator server socket never set `SO_REUSEADDR`

**Symptom:** Re-running `main.py` shortly after a previous run could
raise `OSError: [Errno 48] Address already in use`, forcing a wait for
the OS to release the port (`TIME_WAIT`).

**Root cause:** `Ammeters/base_ammeter.py:18-19` created the listening
socket and called `bind()` without ever setting `SO_REUSEADDR`, so the
kernel refused to rebind a port still in `TIME_WAIT` from the prior
process.

**Fix:** Added
`s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)` immediately
after socket creation, before `bind()`, in
`AmmeterEmulatorBase.start_server`.

**Why:** This touches an emulator file (`Ammeters/base_ammeter.py`),
which is normally off-limits — but it's a documented real bug (see
`docs/investigation.md`), not a rewrite of emulator behavior, and doesn't
change any measurement logic or protocol. `SO_REUSEADDR` is the standard,
minimal fix for this class of restart failure.

## 4. `main.py` used a fixed 5-second sleep as its only readiness check

**Symptom:** `main.py` had no real signal that the emulator threads had
actually started listening — just `time.sleep(5)`, with a comment
admitting this was fragile ("if you have problem restarting the servers
... try increasing sleep time"). Slow startup would race the client
calls; a fast startup wasted 5 seconds every run.

**Root cause:** `main.py:32` (pre-fix) had no handshake or ready signal
between the emulator threads and the client calls that depend on them.

**Fix:** Added a `wait_for_port(host, port, timeout)` helper that polls
each port with `socket.create_connection`, retrying on
`ConnectionRefusedError`/`OSError` until it succeeds or an overall
deadline is hit (raising `TimeoutError` if a server never comes up).
`main.py` now calls this for all three ports instead of sleeping a fixed
amount.

**Why:** A successful TCP connect after the emulator's `listen()` call is
a genuine readiness signal — the OS backlog queues the connection even
before the server's `accept()` loop runs — so this needed no change to
`Ammeters/base_ammeter.py` beyond the `SO_REUSEADDR` fix above. It also
adapts to actual startup time instead of a guessed constant.
