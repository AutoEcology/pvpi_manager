import time

import pytest

from pvpi.transports import ZmqSerialProxyInterface


def test_no_proxy_is_noticed_quickly():
    started = time.monotonic()
    with pytest.raises(ValueError, match="heartbeat"):
        ZmqSerialProxyInterface(addr="tcp://127.0.0.1:1", heartbeat_timeout_ms=200)
    assert time.monotonic() - started < 2
