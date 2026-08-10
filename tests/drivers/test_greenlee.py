from unittest.mock import MagicMock

from src.drivers.greenlee import GreenleeDriver


def test_default_command_matches_verified_protocol():
    assert GreenleeDriver.DEFAULT_COMMAND == b"MEASURE_GREENLEE -get_measurement"


def test_happy_path_sends_exact_command(monkeypatch, greenlee_config):
    instance = MagicMock()
    instance.recv.return_value = b"5.0"
    monkeypatch.setattr(
        "src.drivers.base.socket.socket", MagicMock(return_value=instance)
    )

    driver = GreenleeDriver.from_config("greenlee", greenlee_config)
    sample = driver.measure()

    instance.sendall.assert_called_once_with(b"MEASURE_GREENLEE -get_measurement")
    assert sample.value == 5.0
    assert sample.error is None
