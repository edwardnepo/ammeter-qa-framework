"""Driver for the Greenlee ammeter emulator (Ohm's law: I = V / R)."""

from src.drivers.base import AmmeterDriver


class GreenleeDriver(AmmeterDriver):
    """Greenlee ammeter emulator driver."""

    DEFAULT_COMMAND = b"MEASURE_GREENLEE -get_measurement"
