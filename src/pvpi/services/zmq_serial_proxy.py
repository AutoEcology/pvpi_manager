import asyncio
import logging

import zmq
import zmq.asyncio

from pvpi.transports import SerialInterface

_logger = logging.getLogger(__name__)


class ZmqSerialProxy:
    def __init__(
        self, serial_interface: SerialInterface, bind_addr: str = "tcp://127.0.0.1:5555", timeout_ms: int = 1_000
    ):
        self.serial_interface = serial_interface
        self.bind_addr = bind_addr
        self.timeout_ms = timeout_ms
        self._stay_alive = asyncio.Event()

        self.context = zmq.asyncio.Context()
        self.socket = self.context.socket(zmq.ROUTER)
        self.socket.setsockopt(zmq.RCVTIMEO, timeout_ms)

    async def run(self):
        self.socket.bind(self.bind_addr)
        _logger.info("Running UART proxy & listening at %s", self.bind_addr)
        self._stay_alive.set()
        try:
            while self._stay_alive:
                try:
                    client_id, *payload = await self.socket.recv_multipart()
                except zmq.Again:
                    await asyncio.sleep(0.1)
                    continue
                message: bytes = b"".join(payload)
                _logger.debug("Received request from %s: %s", client_id, message)

                # Proxy heartbeat request
                if message == b"":
                    _logger.debug("Sending heartbeat response to %s", client_id)
                    await self.socket.send_multipart([client_id, b""])
                    continue

                try:
                    response = self.serial_interface.write(message=message)
                except Exception:
                    _logger.warning("Failed to serve client %s", client_id)
                    await self.socket.send_multipart([client_id, b"ERROR"])
                else:
                    _logger.debug("Sending response to %s: %s", client_id, response)
                    await self.socket.send_multipart([client_id, response.encode()])
        finally:
            _logger.info("Closing socket...")
            self.socket.close()
            self.context.term()

    def close(self):
        _logger.info("Signal shutdown")
        self._stay_alive.clear()
