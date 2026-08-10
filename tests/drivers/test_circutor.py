from unittest.mock import MagicMock

from src.drivers.circutor import CircutorDriver


def test_default_command_matches_verified_protocol():
    assert CircutorDriver.DEFAULT_COMMAND == b"MEASURE_CIRCUTOR -get_measurement -current"


def test_happy_path_sends_exact_command(monkeypatch, circutor_config):
    instance = MagicMock()
    instance.recv.return_value = b"0.0123"
    monkeypatch.setattr(
        "src.drivers.base.socket.socket", MagicMock(return_value=instance)
    )

    driver = CircutorDriver.from_config("circutor", circutor_config)
    sample = driver.measure()

    instance.sendall.assert_called_once_with(b"MEASURE_CIRCUTOR -get_measurement -current")
    assert sample.value == 0.0123
    assert sample.error is None
