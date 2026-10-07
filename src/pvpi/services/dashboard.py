"""A small web dashboard: live PV PI readings and charts of the logged history.

The server only reads the CSV logs and asks the UART proxy; the page (dashboard.html) draws
the charts in the browser, so the Pi does little more than serve a few kilobytes of JSON.
"""

import contextlib
import csv
import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pvpi.client import PvPiClient
from pvpi.config import PvPiConfig
from pvpi.transports import ZmqSerialProxyInterface

_logger = logging.getLogger(__name__)

LIVE_CACHE_SECS = 5  # several open pages share one set of readings
DEFAULT_DAYS = 2  # the history shown first: the last two days logged

# CSV column -> the key the page uses
_COLUMNS = {
    "Timestamp": "t",
    "Battery Voltage": "bat_v",
    "Battery Current": "bat_c",
    "PV Voltage": "pv_v",
    "PV Current": "pv_c",
    "PV PI Temperature": "temp",
}


def _proxy_client() -> PvPiClient:
    # Only through the UART proxy: opening the serial port here would take it from the proxy.
    return PvPiClient(interface=ZmqSerialProxyInterface())


def _log_dates(log_dir: Path) -> list[date]:
    """The days there's a log file for, oldest first."""
    found = []
    for file in log_dir.glob("*.csv"):
        try:
            found.append(datetime.strptime(file.stem, "%Y-%m-%d").date())
        except ValueError:
            continue
    return sorted(found)


def read_history(log_dir: Path, start: date | None = None, end: date | None = None) -> dict:
    """The logged readings from `start` to `end` (both included) as one list per column.
    Without dates: the last DEFAULT_DAYS days logged."""
    days = _log_dates(log_dir) if log_dir.is_dir() else []
    first, last = (days[0], days[-1]) if days else (None, None)
    if end is None:
        end = last
    if start is None and end is not None:
        start = max(end - timedelta(days=DEFAULT_DAYS), first or end)

    columns: dict[str, list] = {key: [] for key in _COLUMNS.values()}
    for day in days:
        if start is None or end is None or not start <= day <= end:
            continue
        try:
            with open(log_dir / f"{day:%Y-%m-%d}.csv", newline="") as f:
                for row in csv.DictReader(f, skipinitialspace=True):
                    try:
                        values = {key: row[name] for name, key in _COLUMNS.items()}
                        for key, value in values.items():
                            values[key] = value if key == "t" else float(value)
                    except (KeyError, TypeError, ValueError):
                        continue  # a malformed row
                    for key, value in values.items():
                        columns[key].append(value)
        except (OSError, csv.Error) as err:
            _logger.warning("Skipping %s: %s", day, err)

    def iso(d: date | None) -> str | None:
        return d.isoformat() if d else None

    return {"first": iso(first), "last": iso(last), "start": iso(start), "end": iso(end), "columns": columns}


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, config: PvPiConfig, make_client: Callable[[], PvPiClient] = _proxy_client):
        super().__init__(address, _Handler)
        self.config = config
        self.make_client = make_client
        self._client: PvPiClient | None = None
        self._lock = threading.Lock()  # one request at a time to the board (zmq sockets aren't thread-safe)
        self._live: tuple[float, dict] | None = None

    def live(self) -> dict:
        """The current readings, at most LIVE_CACHE_SECS old. Raises when the board can't be read."""
        with self._lock:
            if self._live and time.monotonic() - self._live[0] < LIVE_CACHE_SECS:
                return self._live[1]
            try:
                if self._client is None:
                    self._client = self.make_client()
                client = self._client
                readings = {
                    "soc": client.estimated_soc(),
                    "bat_v": client.get_battery_voltage(),
                    "bat_c": client.get_battery_current(),
                    "pv_v": client.get_pv_voltage(),
                    "pv_c": client.get_pv_current(),
                    "temp": client.get_board_temp(),
                }
            except Exception:
                self._drop_client()  # try a fresh connection next time
                raise
            readings["time"] = datetime.now().isoformat(timespec="seconds")
            self._live = (time.monotonic(), readings)
            return readings

    def _drop_client(self) -> None:
        if self._client is not None:
            with contextlib.suppress(Exception):
                self._client._interface.close()
        self._client = None

    def server_close(self):
        self._drop_client()
        super().server_close()


# Path -> the package file served there, its type and how long a browser may keep it
_FILES = {
    "/": ("dashboard.html", "text/html; charset=utf-8", "no-store"),
    "/autoecology.png": ("autoecology.png", "image/png", "max-age=86400"),
}


class _Handler(BaseHTTPRequestHandler):
    server: DashboardServer

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in _FILES:
            name, content_type, cache = _FILES[url.path]
            self._send(200, files("pvpi.services").joinpath(name).read_bytes(), content_type, cache)
        elif url.path == "/api/live":
            try:
                readings = self.server.live()
            except Exception as err:
                _logger.warning("Couldn't read the PV PI: %s", err)
                self._json(503, {"error": f"Couldn't read the PV PI: {err}"})
                return
            self._json(200, {**readings, "full_dashboard": self.server.config.full_dashboard})
        elif url.path == "/api/history":
            if not self.server.config.full_dashboard:
                self._json(404, {"error": "full_dashboard is off"})
                return
            query = parse_qs(url.query)
            try:
                start, end = (date.fromisoformat(query[k][0]) if k in query else None for k in ("start", "end"))
            except ValueError:
                self._json(400, {"error": "start and end are dates: YYYY-MM-DD"})
                return
            self._json(200, read_history(Path(self.server.config.data_log_path), start, end))
        else:
            self._json(404, {"error": "not found"})

    def _json(self, status: int, body: dict) -> None:
        self._send(status, json.dumps(body, separators=(",", ":")).encode(), "application/json")

    def _send(self, status: int, body: bytes, content_type: str, cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002 (the base class's name)
        _logger.debug("%s - %s", self.address_string(), format % args)


def run(config: PvPiConfig, host: str = "0.0.0.0", port: int = 8501) -> None:
    server = DashboardServer((host, port), config)
    _logger.info("Dashboard at http://%s:%i", host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
