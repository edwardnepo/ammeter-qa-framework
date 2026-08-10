"""FaultInjectingDriver: a composition wrapper that injects controlled failures.

Wraps any AmmeterDriver instance (not a subclass — composition, not
inheritance) and, at a configurable rate, replaces a real measure() call
with a synthesized fault. This proves the sampler/analyzer/store pipeline
survives and reports bad data correctly instead of crashing, without
touching the drivers layer or the emulators themselves.
"""

import logging
import random
import socket
import time
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Dict, Tuple

from src.drivers.base import AmmeterDriver, MeasurementSample

logger = logging.getLogger(__name__)


class FaultType(str, Enum):
    """The kinds of faults FaultInjectingDriver can synthesize."""

    TIMEOUT = "timeout"
    DISCONNECT = "disconnect"
    CORRUPTED_RESPONSE = "corrupted_response"
    NEGATIVE_VALUE = "negative_value"


@dataclass(frozen=True)
class FaultInjectionConfig:
    """Parameters controlling FaultInjectingDriver's behavior.

    Args:
        fault_rate: Probability in [0, 1] that any given measure() call is
            faulted rather than delegated to the wrapped driver.
        seed: Seed for this config's own random.Random instance, so fault
            sequences are reproducible without touching the global `random`
            module (and without affecting other seeded code in the run).
        fault_types: Which fault kinds are eligible for injection. Must be
            non-empty.
        injected_timeout_seconds: How long a TIMEOUT fault sleeps before
            returning its error sample, so it actually costs wall time
            (visible in the run's duration/jitter) rather than being a
            label with no effect.
    """

    fault_rate: float
    seed: int
    fault_types: Tuple[FaultType, ...]
    injected_timeout_seconds: float = 2.5

    def __post_init__(self) -> None:
        if not 0.0 <= self.fault_rate <= 1.0:
            raise ValueError(f"fault_rate must be in [0, 1], got {self.fault_rate}")
        if not self.fault_types:
            raise ValueError("fault_types must be non-empty")
        if self.injected_timeout_seconds <= 0:
            raise ValueError(
                f"injected_timeout_seconds must be > 0, got {self.injected_timeout_seconds}"
            )

    @classmethod
    def from_config(cls, cfg: Dict[str, Any]) -> "FaultInjectionConfig":
        """Build a FaultInjectionConfig from config.yaml's "fault_injection" sub-dict.

        Args:
            cfg: Must contain "fault_rate" and "seed". May contain
                "fault_types" (defaults to all known types) and
                "injected_timeout_seconds".

        Returns:
            A validated FaultInjectionConfig.

        Raises:
            KeyError: If "fault_rate" or "seed" is missing.
            ValueError: If "fault_rate" is out of [0, 1], "fault_types" is
                empty, or contains an unknown fault type name.
        """
        try:
            fault_rate = cfg["fault_rate"]
            seed = cfg["seed"]
        except KeyError as e:
            raise KeyError(f"fault_injection config is missing required key {e}") from e

        raw_types = cfg.get("fault_types") or [ft.value for ft in FaultType]
        try:
            fault_types = tuple(FaultType(t) for t in raw_types)
        except ValueError as e:
            raise ValueError(f"fault_injection config has an unknown fault type: {e}") from e

        return cls(
            fault_rate=fault_rate,
            seed=seed,
            fault_types=fault_types,
            injected_timeout_seconds=cfg.get("injected_timeout_seconds", 2.5),
        )


class FaultInjectingDriver:
    """Wraps an AmmeterDriver via composition and injects faults into measure().

    Duck-types the same connect()/close()/measure()/context-manager surface
    as AmmeterDriver, so it can be dropped in anywhere a driver is expected
    (e.g. src.testing.sampler.run_sampling), without subclassing it or
    registering as a new driver type in config.yaml.
    """

    def __init__(
        self,
        wrapped: AmmeterDriver,
        fault_config: FaultInjectionConfig,
        name: str,
        unit: str = "A",
    ) -> None:
        """
        Args:
            wrapped: The real AmmeterDriver instance to wrap.
            fault_config: Fault rate, seed, and eligible fault types.
            name: Device identity for synthesized MeasurementSamples.
                Passed explicitly (not read off `wrapped`'s private
                attributes) to keep this a pure composition wrapper.
            unit: Unit label for synthesized MeasurementSamples.
        """
        self._wrapped = wrapped
        self._fault_config = fault_config
        self._name = name
        self._unit = unit
        self._rng = random.Random(fault_config.seed)
        self._injected_count = 0

    @property
    def injected_count(self) -> int:
        """How many measure() calls so far have returned a synthesized fault."""
        return self._injected_count

    def connect(self) -> None:
        """Delegate to the wrapped driver's connect()."""
        self._wrapped.connect()

    def close(self) -> None:
        """Delegate to the wrapped driver's close()."""
        self._wrapped.close()

    def __enter__(self) -> "FaultInjectingDriver":
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def measure(self) -> MeasurementSample:
        """Take one measurement, possibly replaced by a synthesized fault.

        Never raises, mirroring AmmeterDriver.measure()'s own contract:
        run_sampling() calls this in a loop with no try/except, so any
        exception here would abort the whole run.

        Returns:
            A MeasurementSample, either the wrapped driver's real result or
            a synthesized fault.
        """
        if self._rng.random() >= self._fault_config.fault_rate:
            return self._wrapped.measure()

        fault_type = self._rng.choice(self._fault_config.fault_types)
        self._injected_count += 1
        logger.info("%s: injecting fault %s", self._name, fault_type.value)
        return self._inject(fault_type)

    def _inject(self, fault_type: FaultType) -> MeasurementSample:
        """Synthesize a MeasurementSample for the given fault type."""
        if fault_type is FaultType.TIMEOUT:
            return self._inject_timeout()
        if fault_type is FaultType.DISCONNECT:
            return self._inject_disconnect()
        if fault_type is FaultType.CORRUPTED_RESPONSE:
            return self._inject_corrupted_response()
        if fault_type is FaultType.NEGATIVE_VALUE:
            return self._inject_negative_value()
        raise AssertionError(f"unhandled fault type: {fault_type}")  # exhaustive enum

    def _inject_timeout(self) -> MeasurementSample:
        """Simulate a read timeout: sleep, then raise+catch socket.timeout."""
        time.sleep(self._fault_config.injected_timeout_seconds)
        try:
            raise socket.timeout(
                f"injected timeout after {self._fault_config.injected_timeout_seconds}s"
            )
        except socket.timeout as e:
            return self._error_sample(f"injected fault: {e}")

    def _inject_disconnect(self) -> MeasurementSample:
        """Simulate a mid-read disconnect: raise+catch ConnectionResetError."""
        try:
            raise ConnectionResetError("injected connection reset by peer")
        except ConnectionResetError as e:
            return self._error_sample(f"injected fault: {e}")

    def _inject_corrupted_response(self) -> MeasurementSample:
        """Take a real reading, then garble its raw response so it fails to parse."""
        real = self._wrapped.measure()
        garbled = (real.raw_response or "")[::-1] + "#$corrupt"
        return replace(
            real,
            value=None,
            timestamp=time.time(),
            raw_response=garbled,
            error=f"injected fault: corrupted response {garbled!r}",
        )

    def _inject_negative_value(self) -> MeasurementSample:
        """Take a real reading and flip its sign, if it succeeded.

        Deliberately does NOT set `error`: this is a domain-level fault (a
        physically impossible negative current), not a transport-level one.
        It's invisible to failure_count/failure_rate_percent by design —
        see docs/DESIGN.md for why that's the point.
        """
        real = self._wrapped.measure()
        if real.value is None:
            return real
        return replace(real, value=-abs(real.value), timestamp=time.time())

    def _error_sample(self, error: str) -> MeasurementSample:
        """Build a failure MeasurementSample with the current timestamp."""
        return MeasurementSample(
            value=None,
            unit=self._unit,
            timestamp=time.time(),
            device=self._name,
            raw_response=None,
            error=error,
        )
