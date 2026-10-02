import time

import pytest

from pvpi.transports import ZmqSerialProxyInterface


def test_no_proxy_is_noticed_quickly():
    started = time.monotonic()
    with pytest.raises(ValueError, match="heartbeat"):
        ZmqSerialProxyInterface(addr="tcp://127.0.0.1:1", heartbeat_timeout_ms=200)
    assert time.monotonic() - started < 2


@pytest.fixture
def proxy():
    """A stand-in UART proxy (a ROUTER, as the real one): heartbeats answered at once, and
    "SLOW" answered late, after the next request has gone out."""
    import threading

    import zmq

    context = zmq.Context()
    router = context.socket(zmq.ROUTER)
    port = router.bind_to_random_port("tcp://127.0.0.1")
    stop = threading.Event()

    def serve():
        router.setsockopt(zmq.RCVTIMEO, 100)
        while not stop.is_set():
            try:
                client, message = router.recv_multipart()
            except zmq.Again:
                continue
            if message == b"SLOW":
                time.sleep(0.4)
            router.send_multipart([client, b"" if message == b"" else message + b"-reply"])

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield f"tcp://127.0.0.1:{port}"
    stop.set()
    thread.join()
    router.close()
    context.term()


def test_a_late_reply_isnt_taken_as_the_next_requests_answer(proxy):
    import zmq

    client = ZmqSerialProxyInterface(addr=proxy, recv_timeout_ms=200)
    with pytest.raises(zmq.Again):
        client.write(b"SLOW")
    time.sleep(0.4)  # the late SLOW-reply arrives meanwhile
    assert client.write(b"FAST") == "FAST-reply"
    client.close()


def test_two_clients_in_one_process_each_get_their_replies(proxy):
    first = ZmqSerialProxyInterface(addr=proxy)
    second = ZmqSerialProxyInterface(addr=proxy)  # used to share first's identity, and fail
    assert (first.write(b"A"), second.write(b"B")) == ("A-reply", "B-reply")
    first.close()
    second.close()
