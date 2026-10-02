import logging
from typing import Protocol

import serial
import zmq
import zmq.asyncio

from pvpi.utils import default_uart_port

_logger = logging.getLogger(__name__)


class BaseTransportInterface(Protocol):
    def write(self, message: bytes) -> str: ...
    def close(self) -> None: ...


# TODO service stop
# TODO serial not found or similar


class SerialInterface(BaseTransportInterface):
    def __init__(self, port: str | None = None, baud_rate: int = 115_200, timeout_sec: float = 5):
        port = port or default_uart_port()
        self.port = port
        self.baud_rate = baud_rate
        self.timeout_sec = timeout_sec

        # exclusive: a second program opening the port (e.g. while the UART proxy holds it)
        # fails at once instead of mixing its requests and replies with the proxy's.
        self._serial = serial.Serial(
            self.port, self.baud_rate, timeout=self.timeout_sec, write_timeout=self.timeout_sec, exclusive=True
        )
        _logger.info("Successfully opened serial port %s at %i baud.", self.port, self.baud_rate)

    def close(self):
        if self._serial and self._serial.is_open:
            self._serial.close()

    def write(self, message: bytes) -> str:
        try:
            # Drop a reply that came after an earlier request timed out, so it isn't read as
            # the answer to this one.
            self._serial.reset_input_buffer()
            self._serial.write(message)
            _logger.debug("Written to serial: %s", message)

            response = self._serial.readline()
            _logger.debug("Received from serial: %s", response)
            return response.decode().strip()  # remove '\r\n' from responses
        except serial.SerialException as err:
            raise err
        except Exception:
            raise


class ZmqSerialProxyInterface(BaseTransportInterface):
    def __init__(self, addr: str = "tcp://127.0.0.1:5555", recv_timeout_ms=10_000, heartbeat_timeout_ms=1_000):
        self.addr = addr
        self.recv_timeout_ms = recv_timeout_ms

        _logger.info("Connecting to socket at %s", addr)
        self.context = zmq.Context()
        # The heartbeat only waits briefly: a proxy that's running answers it at once.
        self._open(heartbeat_timeout_ms)
        _logger.info("Socket connected")

        if not self.send_heartbeat():
            self.close()
            raise ValueError("ZmqSerialProxyInterface failed heartbeat")
        self.socket.setsockopt(zmq.RCVTIMEO, recv_timeout_ms)  # ms

    def _open(self, recv_timeout_ms: int) -> None:
        # No IDENTITY: the proxy's ROUTER gives each connection its own, so two clients in one
        # process don't share one (the second would never get its replies).
        self.socket = self.context.socket(zmq.DEALER)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.setsockopt(zmq.CONNECT_TIMEOUT, 2_000)  # ms
        self.socket.setsockopt(zmq.RCVTIMEO, recv_timeout_ms)  # ms
        self.socket.connect(self.addr)

    def close(self):
        _logger.info("Closing socket...")
        self.socket.close()
        self.context.term()

    def send_heartbeat(self) -> bool:
        try:
            _logger.info("Sending heartbeat")
            return self.write(b"") == ""
        except Exception:
            _logger.debug("Heartbeat failed to respond")
            return False

    def write(self, message: bytes) -> str:
        self.socket.send_multipart([message])
        _logger.debug("Written to proxy: %s", message)
        try:
            response = b"".join(self.socket.recv_multipart())
            _logger.debug("Received from proxy: %s", response)
        except zmq.Again:
            _logger.debug("Timed out waiting for response from zmq-serial proxy")
            # A fresh socket: the late reply goes to the old one, not to the next request.
            self.socket.close()
            self._open(self.recv_timeout_ms)
            raise
        return response.decode()
