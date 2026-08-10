"""Driver for the ENTES ammeter emulator (Hall effect: I = B * K)."""

from src.drivers.base import AmmeterDriver


class EntesDriver(AmmeterDriver):
    """ENTES ammeter emulator driver."""

    DEFAULT_COMMAND = b"MEASURE_ENTES -get_data"
