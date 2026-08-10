import pytest


@pytest.fixture
def greenlee_config():
    """A minimal ammeter config dict with fast retry timing for tests."""
    return {
        "driver": "src.drivers.greenlee.GreenleeDriver",
        "host": "localhost",
        "port": 5000,
        "command": "MEASURE_GREENLEE -get_measurement",
        "timeout_seconds": 1.0,
        "retries": 3,
        "retry_backoff_seconds": 0.0,
    }


@pytest.fixture
def entes_config():
    """A minimal ammeter config dict with fast retry timing for tests."""
    return {
        "driver": "src.drivers.entes.EntesDriver",
        "host": "localhost",
        "port": 5001,
        "command": "MEASURE_ENTES -get_data",
        "timeout_seconds": 1.0,
        "retries": 3,
        "retry_backoff_seconds": 0.0,
    }


@pytest.fixture
def circutor_config():
    """A minimal ammeter config dict with fast retry timing for tests."""
    return {
        "driver": "src.drivers.circutor.CircutorDriver",
        "host": "localhost",
        "port": 5002,
        "command": "MEASURE_CIRCUTOR -get_measurement -current",
        "timeout_seconds": 1.0,
        "retries": 3,
        "retry_backoff_seconds": 0.0,
    }
