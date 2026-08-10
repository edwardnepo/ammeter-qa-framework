import time
from unittest.mock import MagicMock

import pytest

from src.drivers.base import MeasurementSample
from src.faults.injector import FaultInjectingDriver, FaultInjectionConfig, FaultType


class StubDriver:
    """A minimal AmmeterDriver stand-in with no real socket I/O."""

    def __init__(self, value=10.0, raw_response="10.0", error=None):
        self._value = value
        self._raw_response = raw_response
        self._error = error
        self.connect_calls = 0
        self.close_calls = 0
        self.measure_calls = 0

    def connect(self):
        self.connect_calls += 1

    def close(self):
        self.close_calls += 1

    def measure(self):
        self.measure_calls += 1
        return MeasurementSample(
            value=self._value,
            unit="A",
            timestamp=time.time(),
            device="stub",
            raw_response=self._raw_response,
            error=self._error,
        )


# --- FaultInjectionConfig -----------------------------------------------


def test_from_config_defaults_to_all_fault_types():
    cfg = FaultInjectionConfig.from_config({"fault_rate": 0.5, "seed": 1})
    assert set(cfg.fault_types) == set(FaultType)


def test_from_config_missing_key_raises_keyerror():
    with pytest.raises(KeyError):
        FaultInjectionConfig.from_config({"seed": 1})


def test_from_config_unknown_fault_type_raises_valueerror():
    with pytest.raises(ValueError):
        FaultInjectionConfig.from_config(
            {"fault_rate": 0.5, "seed": 1, "fault_types": ["not_a_real_fault"]}
        )


def test_fault_rate_out_of_range_raises_valueerror():
    with pytest.raises(ValueError):
        FaultInjectionConfig(fault_rate=1.5, seed=1, fault_types=(FaultType.TIMEOUT,))


def test_empty_fault_types_raises_valueerror():
    with pytest.raises(ValueError):
        FaultInjectionConfig(fault_rate=0.5, seed=1, fault_types=())


# --- FaultInjectingDriver: delegation ------------------------------------


def test_fault_rate_zero_always_delegates():
    stub = StubDriver()
    cfg = FaultInjectionConfig(fault_rate=0.0, seed=1, fault_types=tuple(FaultType))
    driver = FaultInjectingDriver(stub, cfg, name="stub")

    for _ in range(20):
        sample = driver.measure()
        assert sample.error is None
        assert sample.value == 10.0

    assert stub.measure_calls == 20
    assert driver.injected_count == 0


def test_connect_and_close_delegate():
    wrapped = MagicMock()
    cfg = FaultInjectionConfig(fault_rate=0.0, seed=1, fault_types=tuple(FaultType))
    driver = FaultInjectingDriver(wrapped, cfg, name="stub")

    driver.connect()
    driver.close()

    wrapped.connect.assert_called_once()
    wrapped.close.assert_called_once()


def test_context_manager_delegates_connect_and_close():
    wrapped = MagicMock()
    cfg = FaultInjectionConfig(fault_rate=0.0, seed=1, fault_types=tuple(FaultType))
    driver = FaultInjectingDriver(wrapped, cfg, name="stub")

    with driver:
        pass

    wrapped.connect.assert_called_once()
    wrapped.close.assert_called_once()


# --- Individual fault types (fault_rate=1.0 isolates one type) ----------


def test_timeout_fault_returns_error_sample_and_sleeps():
    stub = StubDriver()
    cfg = FaultInjectionConfig(
        fault_rate=1.0, seed=1, fault_types=(FaultType.TIMEOUT,), injected_timeout_seconds=0.05
    )
    driver = FaultInjectingDriver(stub, cfg, name="stub")

    start = time.perf_counter()
    sample = driver.measure()
    elapsed = time.perf_counter() - start

    assert sample.value is None
    assert sample.error is not None
    assert "timeout" in sample.error
    assert elapsed >= 0.05
    assert driver.injected_count == 1
    assert stub.measure_calls == 0  # never delegated to the wrapped driver


def test_disconnect_fault_returns_error_sample():
    stub = StubDriver()
    cfg = FaultInjectionConfig(fault_rate=1.0, seed=1, fault_types=(FaultType.DISCONNECT,))
    driver = FaultInjectingDriver(stub, cfg, name="stub")

    sample = driver.measure()

    assert sample.value is None
    assert sample.error is not None
    assert "connection reset" in sample.error
    assert stub.measure_calls == 0


def test_corrupted_response_fault_uses_real_call_then_garbles_it():
    stub = StubDriver(value=42.0, raw_response="42.0")
    cfg = FaultInjectionConfig(fault_rate=1.0, seed=1, fault_types=(FaultType.CORRUPTED_RESPONSE,))
    driver = FaultInjectingDriver(stub, cfg, name="stub")

    sample = driver.measure()

    assert stub.measure_calls == 1  # the real driver was called
    assert sample.value is None
    assert sample.error is not None
    assert "corrupted" in sample.error
    assert sample.raw_response != "42.0"


def test_negative_value_fault_flips_sign_and_sets_no_error():
    stub = StubDriver(value=42.0, raw_response="42.0")
    cfg = FaultInjectionConfig(fault_rate=1.0, seed=1, fault_types=(FaultType.NEGATIVE_VALUE,))
    driver = FaultInjectingDriver(stub, cfg, name="stub")

    sample = driver.measure()

    assert stub.measure_calls == 1
    assert sample.value == -42.0
    assert sample.error is None  # deliberately silent: a domain-level, not transport-level, fault


def test_negative_value_fault_passes_through_genuine_failure_unchanged():
    stub = StubDriver(value=None, raw_response=None, error="genuine failure")
    cfg = FaultInjectionConfig(fault_rate=1.0, seed=1, fault_types=(FaultType.NEGATIVE_VALUE,))
    driver = FaultInjectingDriver(stub, cfg, name="stub")

    sample = driver.measure()

    assert sample.value is None
    assert sample.error == "genuine failure"


# --- measure() never raises ----------------------------------------------


@pytest.mark.parametrize("fault_type", list(FaultType))
def test_measure_never_raises(fault_type):
    stub = StubDriver()
    cfg = FaultInjectionConfig(
        fault_rate=1.0, seed=1, fault_types=(fault_type,), injected_timeout_seconds=0.01
    )
    driver = FaultInjectingDriver(stub, cfg, name="stub")

    sample = driver.measure()  # must not raise

    assert isinstance(sample, MeasurementSample)


# --- Reproducibility -------------------------------------------------------


def test_same_seed_produces_identical_fault_sequence():
    cfg = FaultInjectionConfig(
        fault_rate=0.5, seed=99, fault_types=tuple(FaultType), injected_timeout_seconds=0.001
    )
    driver_a = FaultInjectingDriver(StubDriver(), cfg, name="stub")
    driver_b = FaultInjectingDriver(StubDriver(), cfg, name="stub")

    results_a = [(s.value, s.error) for s in (driver_a.measure() for _ in range(50))]
    results_b = [(s.value, s.error) for s in (driver_b.measure() for _ in range(50))]

    assert results_a == results_b
    assert driver_a.injected_count == driver_b.injected_count
    assert 0 < driver_a.injected_count < 50  # sanity: both faulted and delegated samples occurred


def test_different_seeds_produce_different_fault_sequences():
    cfg_a = FaultInjectionConfig(
        fault_rate=0.5, seed=1, fault_types=tuple(FaultType), injected_timeout_seconds=0.001
    )
    cfg_b = FaultInjectionConfig(
        fault_rate=0.5, seed=2, fault_types=tuple(FaultType), injected_timeout_seconds=0.001
    )
    driver_a = FaultInjectingDriver(StubDriver(), cfg_a, name="stub")
    driver_b = FaultInjectingDriver(StubDriver(), cfg_b, name="stub")

    results_a = [(s.value, s.error) for s in (driver_a.measure() for _ in range(50))]
    results_b = [(s.value, s.error) for s in (driver_b.measure() for _ in range(50))]

    assert results_a != results_b
