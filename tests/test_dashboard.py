import json
import threading
import urllib.error
import urllib.request

import pytest

from pvpi.client import PvPiClient
from pvpi.config import PvPiConfig
from pvpi.services.dashboard import DashboardServer

HEADER = "Timestamp,Battery Voltage,Battery Current,PV Voltage,PV Current,PV PI Temperature\n"
REPLIES = {
    b"GET_BAT_V": "MILLIVOLTS,13200",
    b"GET_BAT_C": "MILLIAMPS,500",
    b"GET_PV_V": "MILLIVOLTS,18000",
    b"GET_PV_C": "MILLIAMPS,1200",
    b"GET_TEMP": "TEMP,25",
}


class Board:
    def __init__(self, working=True):
        self.working = working

    def write(self, message):
        if not self.working:
            raise TimeoutError("no reply")
        return REPLIES[message]

    def close(self):
        pass


def _logs(folder):
    folder.mkdir()
    for day in ("2026-09-10", "2026-09-11", "2026-09-12"):
        (folder / f"{day}.csv").write_text(
            HEADER + f"{day} 07:00:00,13.1,0.0,11.7,0.0,17\n{day} 07:05:00,13.2,0.4,18.1,1.2,19\n"
        )
    (folder / "2026-09-11.csv").open("a").write("2026-09-11 07:10:00,not a number,0,0,0,0\n")  # a malformed row
    (folder / "notes.csv").write_text("not a log\n")


@pytest.fixture
def dashboard(tmp_path):
    """Start a dashboard; returns get(path) -> (status, JSON body or page text)."""
    servers = []

    def start(board=None, full_dashboard=True):
        config = PvPiConfig(data_log_path=tmp_path / "logs", full_dashboard=full_dashboard)
        server = DashboardServer(("127.0.0.1", 0), config, make_client=lambda: PvPiClient(interface=board or Board()))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)

        def get(path):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}{path}") as response:
                    status, body = response.status, response.read().decode()
            except urllib.error.HTTPError as err:
                status, body = err.code, err.read().decode()
            return status, (body if path == "/" else json.loads(body))

        get.port = server.server_port
        return get

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize(
    "path, content_type", [("/", "text/html"), ("/autoecology.png", "image/png"), ("/pvpi.png", "image/png")]
)
def test_the_page_and_logos_are_served(dashboard, path, content_type):
    port = dashboard().port
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as response:
        assert response.status == 200 and response.headers["Content-Type"].startswith(content_type)
        assert response.read()


def test_live_readings(dashboard):
    status, live = dashboard()("/api/live")
    assert status == 200
    assert (live["bat_v"], live["bat_c"], live["pv_v"], live["pv_c"], live["temp"]) == (13.2, 0.5, 18.0, 1.2, 25)
    assert live["soc"] == 80 and live["full_dashboard"] is True


def test_a_board_that_doesnt_answer_is_a_503_and_the_server_keeps_serving(dashboard):
    get = dashboard(board=Board(working=False))
    assert get("/api/live")[0] == 503
    assert get("/api/live")[0] == 503
    assert get("/")[0] == 200


@pytest.mark.parametrize(
    "query, times",
    [
        ("", ["2026-09-10 07:00:00", "2026-09-10 07:05:00", "2026-09-11 07:00:00",
              "2026-09-11 07:05:00", "2026-09-12 07:00:00", "2026-09-12 07:05:00"]),  # the last two days, and the one before
        ("?start=2026-09-11&end=2026-09-11", ["2026-09-11 07:00:00", "2026-09-11 07:05:00"]),
        ("?start=2026-09-12", ["2026-09-12 07:00:00", "2026-09-12 07:05:00"]),
        ("?start=2026-10-01&end=2026-10-02", []),
    ],
)  # fmt: skip
def test_history_reads_the_days_asked_for(dashboard, tmp_path, query, times):
    _logs(tmp_path / "logs")
    status, history = dashboard()("/api/history" + query)
    assert status == 200
    assert history["columns"]["t"] == times
    assert len(history["columns"]["pv_v"]) == len(times)
    assert (history["first"], history["last"]) == ("2026-09-10", "2026-09-12")


def test_history_with_no_logs_is_empty(dashboard):
    status, history = dashboard()("/api/history")
    assert status == 200 and history["columns"]["t"] == [] and history["first"] is None


@pytest.mark.parametrize("query, status", [("?start=yesterday", 400), ("", 404)])
def test_history_refusals(dashboard, query, status):
    get = dashboard(full_dashboard=query != "")
    assert get("/api/history" + query)[0] == status
