"""A small web dashboard: live PV PI readings and charts of the logged history.

The server only reads the CSV logs and asks the UART proxy; the page (dashboard.html) draws
the charts in the browser, so the Pi does little more than serve a few kilobytes of JSON.
"""

import contextlib
import csv
import json
import logging
import re
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pydantic import ValidationError

from pvpi.client import PvPiClient
from pvpi.config import SCHEDULE_NAME, PvPiConfig
from pvpi.schedule import Schedule
from pvpi.transports import ZmqSerialProxyInterface

_logger = logging.getLogger(__name__)

LIVE_CACHE_SECS = 5  # several open pages share one set of readings
MAX_BODY = 64 * 1024  # a schedule is a few hundred bytes
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


def _errors(err: ValidationError) -> list[str]:
    """Pydantic's errors as short lines, e.g. "Rule 1, on: Input should be in a valid time format"."""
    found = []
    for e in err.errors():
        loc = [str(x) for x in e["loc"]]
        if loc[:1] == ["rules"] and len(loc) > 1:
            where = f"Rule {int(loc[1]) + 1}" + "".join(f", {x}" for x in loc[3:])  # skip the rule's kind
        else:
            where = ", ".join(loc) or "Schedule"
        found.append(f"{where}: {e['msg']}")
    return found


def check_schedule(config: PvPiConfig, body, now: datetime | None = None) -> dict:
    """What the schedule page shows for a schedule: what's wrong with it and its next 24 hours."""
    now = (now or datetime.now()).replace(microsecond=0)
    try:
        schedule = Schedule.model_validate(body)
    except ValidationError as err:
        return {"errors": _errors(err), "problems": [], "periods": []}
    alarm = schedule.alarm(now + config.min_off)
    return {
        "errors": [],
        "problems": config.check_schedule(schedule),
        "now": now.isoformat(),
        "on": schedule.is_on(now),
        "periods": [[a.isoformat(), b.isoformat()] for a, b in schedule.periods(now, now + timedelta(hours=24))],
        "alarm": alarm.isoformat() if alarm else None,
    }


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, config: PvPiConfig, make_client: Callable[[], PvPiClient] = _proxy_client):
        super().__init__(address, _Handler)
        self.config = config
        self.make_client = make_client
        self._client: PvPiClient | None = None
        self._lock = threading.Lock()  # one request at a time to the board (zmq sockets aren't thread-safe)
        self.files_lock = threading.Lock()  # one change at a time to the config and schedule files
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
    "/schedule": ("schedule.html", "text/html; charset=utf-8", "no-store"),
    "/dashboard.css": ("dashboard.css", "text/css; charset=utf-8", "no-store"),
    "/common.js": ("common.js", "text/javascript; charset=utf-8", "no-store"),
    "/autoecology.png": ("autoecology.png", "image/png", "max-age=86400"),
    "/pvpi.png": ("pvpi.png", "image/png", "max-age=86400"),
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
        elif url.path == "/api/schedules":
            self._json(200, self._schedules())
        elif name := self._schedule_name(url.path):
            path = self.server.config.schedule_path(name)
            if not path.exists():
                self._json(404, {"error": f"No schedule '{name}'"})
                return
            try:
                self._json(200, {"name": name, **json.loads(path.read_text())})
            except (OSError, ValueError) as err:
                self._json(500, {"error": f"Can't read schedule '{name}': {err}"})
        else:
            self._json(404, {"error": "not found"})

    # The schedule page: schedule files in the config's schedules folder, and the one in use.

    def do_POST(self):
        body = self._body()
        if body is None:
            return
        if self.path == "/api/schedules/check":
            self._json(200, check_schedule(self.server.config, body))
        elif self.path == "/api/schedules/active":
            name = body.get("name") if isinstance(body, dict) else None
            with self.server.files_lock:
                if name is not None:
                    if not isinstance(name, str) or not re.fullmatch(SCHEDULE_NAME, name):
                        self._json(400, {"error": "A schedule's name is letters, numbers, - and _"})
                        return
                    path = self.server.config.schedule_path(name)
                    if not path.exists():
                        self._json(404, {"error": f"No schedule '{name}'"})
                        return
                    checked = check_schedule(self.server.config, json.loads(path.read_text()))
                    if checked["errors"] or checked["problems"]:
                        self._json(400, {"error": f"Schedule '{name}' can't be used", **checked})
                        return
                self._set_active(name)
            self._json(200, self._schedules())
        else:
            self._json(404, {"error": "not found"})

    def do_PUT(self):
        name = self._schedule_name(self.path)
        if not name:
            self._json(404, {"error": "not found"})
            return
        body = self._body()
        if body is None:
            return
        checked = check_schedule(self.server.config, body)
        if checked["errors"] or checked["problems"]:
            self._json(400, {"error": "The schedule can't be used", **checked})
            return
        with self.server.files_lock:
            Schedule.model_validate(body).save(self.server.config.schedule_path(name))
        self._json(200, {"name": name, **checked})

    def do_DELETE(self):
        name = self._schedule_name(self.path)
        if not name:
            self._json(404, {"error": "not found"})
            return
        with self.server.files_lock:
            if name == self.server.config.schedule:
                self._json(409, {"error": f"'{name}' is in use: choose another schedule first"})
                return
            path = self.server.config.schedule_path(name)
            if not path.exists():
                self._json(404, {"error": f"No schedule '{name}'"})
                return
            path.unlink()
        self._json(200, self._schedules())

    def _schedule_name(self, path: str) -> str | None:
        """The NAME in /api/schedules/NAME; None for any other path (so no path can be given)."""
        found = re.fullmatch(r"/api/schedules/(.+)", urlparse(path).path)
        if found and found.group(1) not in ("check", "active") and re.fullmatch(SCHEDULE_NAME, found.group(1)):
            return found.group(1)
        return None

    def _schedules(self) -> dict:
        folder = self.server.config.schedules_folder
        names = sorted(p.stem for p in folder.glob("*.json") if re.fullmatch(SCHEDULE_NAME, p.stem))
        return {"active": self.server.config.schedule, "folder": str(folder), "schedules": names}

    def _set_active(self, name: str | None) -> None:
        """Choose the schedule in use, in the config file the manager reads (it picks it up)."""
        config = self.server.config
        if config._source is not None:
            config = PvPiConfig.from_file(str(config._source))  # as it is on disk now
        config.schedule = name
        if config._source is not None:
            config.save(config._source)
        self.server.config = config

    def _body(self):
        """The request's JSON, or None after answering 400."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_BODY:
                raise ValueError("too long")
            return json.loads(self.rfile.read(length) or b"null")
        except ValueError as err:
            self._json(400, {"error": f"Expected JSON: {err}"})
            return None

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
