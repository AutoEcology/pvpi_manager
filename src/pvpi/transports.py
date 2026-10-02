import logging
import os
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

        self._serial = serial.Serial(
            self.port, self.baud_rate, timeout=self.timeout_sec, write_timeout=self.timeout_sec
        )
        _logger.info("Successfully opened serial port %s at %i baud.", self.port, self.baud_rate)

    def close(self):
        if self._serial and self._serial.is_open:
            self._serial.close()

    def write(self, message: bytes) -> str:
        try:
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

        _logger.info("Connecting to socket at %s", addr)
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.DEALER)
        self.client_id = f"client_pid#{os.getpid()}".encode()
        self.socket.setsockopt(zmq.IDENTITY, self.client_id)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.setsockopt(zmq.CONNECT_TIMEOUT, 2_000)  # ms
        # The heartbeat only waits briefly: a proxy that's running answers it at once.
        self.socket.setsockopt(zmq.RCVTIMEO, heartbeat_timeout_ms)  # ms
        self.socket.connect(self.addr)
        _logger.info("Socket connected")

        if not self.send_heartbeat():
            self.close()
            raise ValueError("ZmqSerialProxyInterface failed heartbeat")
        self.socket.setsockopt(zmq.RCVTIMEO, recv_timeout_ms)  # ms

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
            raise
        return response.decode()
