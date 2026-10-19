"""The power log: when the Pi booted and shut down, and the manager's heartbeat while it runs.

One CSV a day in `<data_log_path>/power/`, kept as long as the readings. Each row is
`Timestamp, Event, Reason, Boot time`, the event one of:
- `boot`: the manager started in this boot (once per boot, also if the manager restarts);
- `running`: the manager's heartbeat, every `heartbeat_mins`;
- `shutdown`: the manager shut the Pi down, the reason `schedule` or `low battery`.

A boot with no `shutdown` row ended unexpectedly (power lost, or a crash), after its last row.
"""

import csv
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from pvpi.logging_ import POWER_HEADERS, TIME_FORMAT, RotatingCSVLogger

FOLDER = "power"
SAME_BOOT = timedelta(seconds=60)  # boot times this close are one boot (each is worked out from the uptime)


def boot_time() -> datetime:
    """When this boot began, from the uptime, so a clock set since then doesn't move it."""
    with open("/proc/uptime") as f:
        uptime = float(f.read().split()[0])
    return (datetime.now() - timedelta(seconds=uptime)).replace(microsecond=0)


def _rows(folder: Path, first: date, last: date) -> list[dict]:
    """The rows logged from `first` to `last` (both included), oldest first."""
    found = []
    day = first
    while day <= last:
        try:
            with open(folder / f"{day:%Y-%m-%d}.csv", newline="") as f:
                for row in csv.DictReader(f):
                    try:
                        found.append(
                            {
                                "t": datetime.strptime(row["Timestamp"], TIME_FORMAT),
                                "event": row["Event"],
                                "reason": row.get("Reason") or "",
                                "boot": datetime.strptime(row["Boot time"], TIME_FORMAT),
                            }
                        )
                    except (KeyError, TypeError, ValueError):
                        continue  # a malformed row
        except OSError:
            pass
        day += timedelta(days=1)
    return sorted(found, key=lambda r: r["t"])


class PowerLog:
    def __init__(self, data_log_path: Path, retention_days: int, heartbeat_mins: int, boot: datetime | None = None):
        self.folder = Path(data_log_path) / FOLDER
        self._csv = RotatingCSVLogger(self.folder, retention_days, POWER_HEADERS)
        self.boot = boot or boot_time()
        self.heartbeat_secs = heartbeat_mins * 60
        self._last_beat: float | None = None

    def started(self) -> None:
        """Log this boot, unless the manager already did (it was restarted)."""
        today = date.today()
        if any(abs(r["boot"] - self.boot) < SAME_BOOT for r in _rows(self.folder, today - timedelta(days=1), today)):
            return
        self._write("boot")

    def beat(self) -> None:
        """Log the heartbeat if one is due."""
        now = time.monotonic()
        if self._last_beat is None or now - self._last_beat >= self.heartbeat_secs:
            self._write("running")
            self._last_beat = now

    def shutdown(self, reason: str) -> None:
        self._write("shutdown", reason)

    def _write(self, event: str, reason: str = "") -> None:
        self._csv.log(event, reason, self.boot.strftime(TIME_FORMAT))


def read_power(
    data_log_path: Path, start: datetime, end: datetime, heartbeat_mins: int, current_boot: datetime | None = None
) -> dict:
    """From `start` to `end`: when the Pi was on and the manager running, and each boot and shutdown.

    - `on`: [boot, end, how it ended]: `schedule`, `low battery`, `unexpected`, or `running` for
      `current_boot` (still on, so it ends now);
    - `running`: [first, last] heartbeats with no gap over two heartbeat periods;
    - `boots` and `shutdowns` ([time, reason]): the moments, for markers.
    """
    folder = Path(data_log_path) / FOLDER
    rows = _rows(folder, start.date() - timedelta(days=1), end.date())
    now = datetime.now().replace(microsecond=0)

    by_boot: dict[datetime, list[dict]] = {}
    for row in rows:
        key = next((b for b in by_boot if abs(b - row["boot"]) < SAME_BOOT), row["boot"])
        by_boot.setdefault(key, []).append(row)
    on = []
    for boot, boot_rows in by_boot.items():
        down = next((r for r in boot_rows if r["event"] == "shutdown"), None)
        if down:
            finish, how = down["t"], down["reason"] or "unexpected"
        elif current_boot is not None and abs(boot - current_boot) < SAME_BOOT:
            finish, how = now, "running"
        else:
            finish, how = boot_rows[-1]["t"], "unexpected"
        if finish > start and boot < end:
            on.append([boot, finish, how])

    gap = timedelta(minutes=2 * heartbeat_mins)
    running: list[list[datetime]] = []
    for row in rows:
        if running and row["t"] - running[-1][1] <= gap and abs(row["boot"] - running[-1][2]) < SAME_BOOT:
            running[-1][1] = row["t"]
        else:
            running.append([row["t"], row["t"], row["boot"]])
    running = [[a, b] for a, b, _ in running if b >= start and a < end]

    def iso(t: datetime) -> str:
        return t.isoformat(timespec="seconds")

    return {
        "on": [[iso(max(a, start)), iso(min(b, end)), how] for a, b, how in on],
        "running": [[iso(max(a, start)), iso(min(b, end))] for a, b in running],
        "boots": [iso(b) for b, *_ in on if start <= b < end],
        "shutdowns": [[iso(r["t"]), r["reason"]] for r in rows if r["event"] == "shutdown" and start <= r["t"] < end],
    }
