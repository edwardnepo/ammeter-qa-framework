import socket
import threading
import time

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from Ammeters.client import request_current_from_ammeter

READINESS_TIMEOUT_SECONDS = 5.0
READINESS_POLL_INTERVAL_SECONDS = 0.05


def run_greenlee_emulator():
    greenlee = GreenleeAmmeter(5000)
    greenlee.start_server()

def run_entes_emulator():
    entes = EntesAmmeter(5001)
    entes.start_server()

def run_circutor_emulator():
    circutor = CircutorAmmeter(5002)
    circutor.start_server()

def wait_for_port(host: str, port: int, timeout: float) -> None:
    """
    Block until a TCP server is accepting connections on host:port.

    A successful connect is a real readiness signal even before the
    server's accept() loop runs a first iteration, since a listening
    socket's backlog queues the connection.

    Args:
        host: Hostname or IP address of the server to poll.
        port: TCP port to poll.
        timeout: Maximum number of seconds to wait before giving up.

    Raises:
        TimeoutError: If no server is accepting connections on
            host:port within `timeout` seconds.
    """
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        try:
            with socket.create_connection((host, port), timeout=READINESS_POLL_INTERVAL_SECONDS):
                return
        except (ConnectionRefusedError, OSError):
            time.sleep(READINESS_POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"No server became ready on {host}:{port} within {timeout}s")

if __name__ == "__main__":
    # Start each ammeter in a separate thread
    threading.Thread(target=run_greenlee_emulator, daemon=True).start()
    threading.Thread(target=run_entes_emulator, daemon=True).start()
    threading.Thread(target=run_circutor_emulator, daemon=True).start()

    for port in (5000, 5001, 5002):
        wait_for_port("localhost", port, READINESS_TIMEOUT_SECONDS)

    request_current_from_ammeter(5000, b'MEASURE_GREENLEE -get_measurement')  # Request from Greenlee Ammeter
    request_current_from_ammeter(5001, b'MEASURE_ENTES -get_data')  # Request from ENTES Ammeter
    request_current_from_ammeter(5002, b'MEASURE_CIRCUTOR -get_measurement -current')  # Request from CIRCUTOR Ammeter
