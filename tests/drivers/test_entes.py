from unittest.mock import MagicMock

from src.drivers.entes import EntesDriver


def test_default_command_matches_verified_protocol():
    assert EntesDriver.DEFAULT_COMMAND == b"MEASURE_ENTES -get_data"


def test_happy_path_sends_exact_command(monkeypatch, entes_config):
    instance = MagicMock()
    instance.recv.return_value = b"42.0"
    monkeypatch.setattr(
        "src.drivers.base.socket.socket", MagicMock(return_value=instance)
    )

    driver = EntesDriver.from_config("entes", entes_config)
    sample = driver.measure()

    instance.sendall.assert_called_once_with(b"MEASURE_ENTES -get_data")
    assert sample.value == 42.0
    assert sample.error is None
