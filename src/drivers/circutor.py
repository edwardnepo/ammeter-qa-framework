"""Driver for the CIRCUTOR ammeter emulator (Rogowski coil: I = sum(V_i * dt))."""

from src.drivers.base import AmmeterDriver


class CircutorDriver(AmmeterDriver):
    """CIRCUTOR ammeter emulator driver."""

    DEFAULT_COMMAND = b"MEASURE_CIRCUTOR -get_measurement -current"
