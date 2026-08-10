import socket
from unittest.mock import MagicMock

import pytest

from src.drivers.greenlee import GreenleeDriver


@pytest.fixture
def mock_socket(monkeypatch):
    """Patch src.drivers.base.socket.socket to return one shared mock instance."""
    instance = MagicMock(name="socket_instance")
    socket_class = MagicMock(name="socket_class", return_value=instance)
    monkeypatch.setattr("src.drivers.base.socket.socket", socket_class)
    return socket_class, instance


@pytest.fixture
def no_sleep(monkeypatch):
    """Patch src.drivers.base.time.sleep so retry backoff doesn't actually wait."""
    sleep_mock = MagicMock()
    monkeypatch.setattr("src.drivers.base.time.sleep", sleep_mock)
    return sleep_mock


def test_measure_success(greenlee_config, mock_socket, no_sleep):
    socket_class, instance = mock_socket
    instance.recv.return_value = b"3.14"

    driver = GreenleeDriver.from_config("greenlee", greenlee_config)
    sample = driver.measure()

    assert sample.value == 3.14
    assert sample.unit == "A"
    assert sample.device == "greenlee"
    assert sample.raw_response == "3.14"
    assert sample.error is None
    instance.sendall.assert_called_once_with(b"MEASURE_GREENLEE -get_measurement")


def test_measure_timeout_retries_then_returns_error(greenlee_config, mock_socket, no_sleep):
    socket_class, instance = mock_socket
    instance.recv.side_effect = socket.timeout()

    driver = GreenleeDriver.from_config("greenlee", greenlee_config)
    sample = driver.measure()

    assert sample.value is None
    assert sample.error is not None
    assert "timed out" in sample.error
    assert socket_class.call_count == greenlee_config["retries"]
    assert no_sleep.call_count == greenlee_config["retries"] - 1


def test_measure_malformed_response_not_retried(greenlee_config, mock_socket, no_sleep):
    socket_class, instance = mock_socket
    instance.recv.return_value = b"NOT_A_NUMBER"

    driver = GreenleeDriver.from_config("greenlee", greenlee_config)
    sample = driver.measure()

    assert sample.value is None
    assert sample.raw_response == "NOT_A_NUMBER"
    assert "non-numeric" in sample.error
    assert socket_class.call_count == 1
    no_sleep.assert_not_called()


def test_measure_empty_response_not_retried(greenlee_config, mock_socket, no_sleep):
    socket_class, instance = mock_socket
    instance.recv.return_value = b""

    driver = GreenleeDriver.from_config("greenlee", greenlee_config)
    sample = driver.measure()

    assert sample.value is None
    assert sample.raw_response is None
    assert "empty response" in sample.error
    assert socket_class.call_count == 1
    no_sleep.assert_not_called()


def test_connect_raises_after_retries_exhausted(greenlee_config, mock_socket, no_sleep):
    socket_class, instance = mock_socket
    instance.connect.side_effect = ConnectionRefusedError()

    driver = GreenleeDriver.from_config("greenlee", greenlee_config)

    with pytest.raises(ConnectionError):
        driver.connect()
    assert socket_class.call_count == greenlee_config["retries"]


def test_context_manager_closes_on_exception(greenlee_config, mock_socket, no_sleep):
    socket_class, instance = mock_socket

    driver = GreenleeDriver.from_config("greenlee", greenlee_config)

    with pytest.raises(ValueError):
        with driver:
            raise ValueError("boom")
    instance.close.assert_called_once()


def test_close_without_connect_is_noop(greenlee_config):
    driver = GreenleeDriver.from_config("greenlee", greenlee_config)
    driver.close()
    driver.close()


def test_close_after_connect_is_idempotent(greenlee_config, mock_socket, no_sleep):
    socket_class, instance = mock_socket

    driver = GreenleeDriver.from_config("greenlee", greenlee_config)
    driver.connect()
    driver.close()
    driver.close()

    instance.close.assert_called_once()


def test_from_config_missing_host_raises_keyerror(greenlee_config):
    del greenlee_config["host"]
    with pytest.raises(KeyError):
        GreenleeDriver.from_config("greenlee", greenlee_config)


def test_init_rejects_invalid_retries():
    with pytest.raises(ValueError):
        GreenleeDriver(
            name="greenlee", host="localhost", port=5000,
            command=b"cmd", retries=0,
        )


def test_init_rejects_invalid_timeout():
    with pytest.raises(ValueError):
        GreenleeDriver(
            name="greenlee", host="localhost", port=5000,
            command=b"cmd", timeout=0,
        )
