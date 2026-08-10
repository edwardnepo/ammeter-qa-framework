"""AmmeterDriver: shared TCP wire protocol for all ammeter emulators."""

import logging
import socket
import time
from abc import ABC
from dataclasses import dataclass
from typing import Any, ClassVar, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MeasurementSample:
    """One measurement attempt's outcome, success or failure.

    Args:
        value: Parsed current reading, or None if the attempt failed.
        unit: Unit label for `value` (e.g. "A").
        timestamp: `time.time()` epoch seconds when the sample was taken.
        device: Config key identifying which ammeter produced this sample.
        raw_response: Decoded response string, or None if nothing was
            received (empty reply or failure before any bytes arrived).
        error: None on success; a human-readable failure reason otherwise.
    """

    value: Optional[float]
    unit: str
    timestamp: float
    device: str
    raw_response: Optional[str]
    error: Optional[str] = None


class AmmeterDriver(ABC):
    """Template-Method base class for the ammeter emulators' TCP protocol.

    Every emulator speaks the same unframed protocol: open a TCP
    connection, send an exact command, read up to 1024 bytes. A
    byte-for-byte command match yields an ASCII float reply; anything
    else yields an empty reply and the connection is closed by the
    server either way. Vendor subclasses supply only DEFAULT_COMMAND
    (and optionally DEFAULT_UNIT) as class-level fallbacks.
    """

    DEFAULT_COMMAND: ClassVar[Optional[bytes]] = None
    DEFAULT_UNIT: ClassVar[str] = "A"

    def __init__(
        self,
        name: str,
        host: str,
        port: int,
        command: bytes,
        unit: str = "A",
        timeout: float = 2.0,
        retries: int = 3,
        retry_backoff: float = 0.5,
    ) -> None:
        """
        Args:
            name: Config key / device identity, e.g. "greenlee". Used as
                MeasurementSample.device and in log messages.
            host: Hostname/IP to connect to.
            port: TCP port to connect to.
            command: Exact command bytes to send. The emulator requires
                byte-for-byte equality.
            unit: Unit label attached to every MeasurementSample.
            timeout: Seconds applied to both the TCP connect and the
                recv() call via socket.settimeout().
            retries: Maximum number of attempts (not additional retries)
                for both connect() and measure(). Must be >= 1.
            retry_backoff: Seconds to sleep between attempts.

        Raises:
            ValueError: If retries < 1 or timeout <= 0.
        """
        if retries < 1:
            raise ValueError(f"retries must be >= 1, got {retries}")
        if timeout <= 0:
            raise ValueError(f"timeout must be > 0, got {timeout}")

        self._name = name
        self._host = host
        self._port = port
        self._command = command
        self._unit = unit
        self._timeout = timeout
        self._retries = retries
        self._retry_backoff = retry_backoff
        self._sock: Optional[socket.socket] = None

    @classmethod
    def from_config(cls, name: str, cfg: Dict[str, Any]) -> "AmmeterDriver":
        """Build a driver from one ammeter's config.yaml sub-dict.

        Args:
            name: The ammeter's config key.
            cfg: Must contain "host" and "port". May contain "command"
                (falls back to cls.DEFAULT_COMMAND if absent), "unit",
                "timeout_seconds", "retries", "retry_backoff_seconds".

        Returns:
            A constructed, not-yet-connected driver instance.

        Raises:
            KeyError: If "host" or "port" is missing.
            ValueError: If cfg has no "command" and the class has no
                DEFAULT_COMMAND fallback.
        """
        try:
            host = cfg["host"]
            port = cfg["port"]
        except KeyError as e:
            raise KeyError(f"ammeter '{name}' config is missing required key {e}") from e

        command_str = cfg.get("command")
        if command_str is not None:
            command = command_str.encode("utf-8")
        elif cls.DEFAULT_COMMAND is not None:
            command = cls.DEFAULT_COMMAND
        else:
            raise ValueError(
                f"ammeter '{name}' config has no 'command' and {cls.__name__} "
                "defines no DEFAULT_COMMAND fallback"
            )

        return cls(
            name=name,
            host=host,
            port=port,
            command=command,
            unit=cfg.get("unit", cls.DEFAULT_UNIT),
            timeout=cfg.get("timeout_seconds", 2.0),
            retries=cfg.get("retries", 3),
            retry_backoff=cfg.get("retry_backoff_seconds", 0.5),
        )

    @property
    def command(self) -> bytes:
        """The exact bytes this driver sends to request a measurement."""
        return self._command

    def _connect_once(self) -> socket.socket:
        """Open a single fresh TCP connection, no retry.

        Returns:
            A connected socket with `timeout` applied.

        Raises:
            socket.timeout: If the connection attempt times out.
            OSError: For any other connection failure (e.g. refused).
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self._timeout)
        try:
            sock.connect((self._host, self._port))
        except (socket.timeout, OSError):
            sock.close()
            raise
        return sock

    def connect(self) -> None:
        """Open and hold a connection, retrying transient failures.

        Standalone reachability preflight; does not send the measurement
        command. Safe to call before the first measure(), or not at all.

        Raises:
            ConnectionError: If no connection could be established after
                `retries` attempts. Chains the last underlying error.
        """
        last_error: Optional[BaseException] = None
        for attempt in range(1, self._retries + 1):
            try:
                self._sock = self._connect_once()
                return
            except socket.timeout as e:
                last_error = e
                logger.warning(
                    "%s: connect attempt %d/%d to %s:%d timed out",
                    self._name, attempt, self._retries, self._host, self._port,
                )
            except OSError as e:
                last_error = e
                logger.warning(
                    "%s: connect attempt %d/%d to %s:%d failed: %s",
                    self._name, attempt, self._retries, self._host, self._port, e,
                )
            if attempt < self._retries:
                time.sleep(self._retry_backoff)

        raise ConnectionError(
            f"{self._name}: failed to connect to {self._host}:{self._port} "
            f"after {self._retries} attempts"
        ) from last_error

    def measure(self) -> MeasurementSample:
        """Take one measurement: connect, send command, read, parse.

        Retries the whole connect+send+recv cycle up to `retries` times
        for transient channel errors only (connect failure, timeout,
        reset/broken pipe). An empty reply (protocol/command mismatch)
        or a non-numeric reply is deterministic, not transient, and is
        returned immediately as a single-attempt error without retry.

        Never raises for network/protocol failures — always returns a
        MeasurementSample, with `error` set on any failure.

        Returns:
            A MeasurementSample; `error` is None on success.
        """
        last_error: Optional[str] = None

        for attempt in range(1, self._retries + 1):
            sock: Optional[socket.socket] = None
            try:
                sock = self._connect_once()
                sock.sendall(self._command)
                data = sock.recv(1024)
            except socket.timeout as e:
                last_error = f"read timed out after {self._timeout}s"
                logger.warning(
                    "%s: measure attempt %d/%d timed out: %s",
                    self._name, attempt, self._retries, e,
                )
                if attempt < self._retries:
                    time.sleep(self._retry_backoff)
                continue
            except OSError as e:
                last_error = str(e)
                logger.warning(
                    "%s: measure attempt %d/%d failed: %s",
                    self._name, attempt, self._retries, e,
                )
                if attempt < self._retries:
                    time.sleep(self._retry_backoff)
                continue
            finally:
                if sock is not None:
                    sock.close()

            if data == b"":
                return self._error_sample(
                    "empty response (protocol/command mismatch)", raw_response=None
                )

            raw_response = data.decode("utf-8", errors="replace")
            try:
                value = float(raw_response)
            except ValueError:
                return self._error_sample(
                    f"non-numeric response: {raw_response!r}", raw_response=raw_response
                )

            return MeasurementSample(
                value=value,
                unit=self._unit,
                timestamp=time.time(),
                device=self._name,
                raw_response=raw_response,
                error=None,
            )

        return self._error_sample(
            f"failed after {self._retries} attempts: {last_error}", raw_response=None
        )

    def _error_sample(self, error: str, raw_response: Optional[str]) -> MeasurementSample:
        """Build a failure MeasurementSample with the current timestamp."""
        return MeasurementSample(
            value=None,
            unit=self._unit,
            timestamp=time.time(),
            device=self._name,
            raw_response=raw_response,
            error=error,
        )

    def close(self) -> None:
        """Idempotently close the connection opened by connect(). Never raises."""
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError as e:
                logger.debug("%s: error closing socket: %s", self._name, e)
            finally:
                self._sock = None

    def __enter__(self) -> "AmmeterDriver":
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()
