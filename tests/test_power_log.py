"""The power log: what's written for a boot, the heartbeat and a shutdown, and what's read back."""

from datetime import datetime, timedelta

import pytest

from pvpi import power_log
from pvpi.logging_ import POWER_HEADERS
from pvpi.power_log import PowerLog, read_power

BOOT = datetime(2026, 10, 19, 7, 0, 40)
DAY = (datetime(2026, 10, 19), datetime(2026, 10, 20))


def rows(tmp_path):
    lines = []
    for f in sorted((tmp_path / "power").glob("*.csv")):
        lines += f.read_text().splitlines()[1:]
    return [line.split(",") for line in lines]


def write(tmp_path, *entries):
    """entries: (time, event, reason, boot time), as logged."""
    folder = tmp_path / "power"
    folder.mkdir(exist_ok=True)
    for t, event, reason, boot in entries:
        path = folder / f"{t:%Y-%m-%d}.csv"
        if not path.exists():
            path.write_text(",".join(POWER_HEADERS) + "\n")
        with path.open("a") as f:
            f.write(f"{t:%Y-%m-%d %H:%M:%S},{event},{reason},{boot:%Y-%m-%d %H:%M:%S}\n")


def beats(boot, first, last, every=timedelta(minutes=1)):
    t, found = first, []
    while t <= last:
        found.append((t, "running", "", boot))
        t += every
    return found


def test_a_boot_is_logged_once_also_when_the_manager_restarts(tmp_path):
    PowerLog(tmp_path, 7, 1, boot=BOOT).started()
    PowerLog(tmp_path, 7, 1, boot=BOOT + timedelta(seconds=1)).started()  # the uptime gives a second either way
    assert [r[1] for r in rows(tmp_path)] == ["boot"]


def test_the_heartbeat_is_written_every_heartbeat_mins(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(power_log.time, "monotonic", lambda: clock[0])
    log = PowerLog(tmp_path, 7, 2, boot=BOOT)
    for _ in range(25):  # 10 s passes for 4 minutes
        log.beat()
        clock[0] += 10
    log.shutdown("schedule")
    assert [r[1] for r in rows(tmp_path)] == ["running", "running", "running", "shutdown"]
    assert rows(tmp_path)[-1][2:] == ["schedule", "2026-10-19 07:00:40"]


def test_a_day_with_a_scheduled_shutdown(tmp_path):
    down = datetime(2026, 10, 19, 19, 0, 2)
    write(tmp_path, (BOOT + timedelta(seconds=20), "boot", "", BOOT), *beats(BOOT, BOOT + timedelta(seconds=21), down))
    write(tmp_path, (down, "shutdown", "schedule", BOOT))
    power = read_power(tmp_path, *DAY, heartbeat_mins=1)
    assert power["on"] == [["2026-10-19T07:00:40", "2026-10-19T19:00:02", "schedule"]]
    assert power["running"] == [["2026-10-19T07:00:40", "2026-10-19T19:00:02"]]  # from the boot
    assert power["boots"] == ["2026-10-19T07:00:40"] and power["shutdowns"] == [["2026-10-19T19:00:02", "schedule"]]


def test_a_boot_with_no_shutdown_ended_unexpectedly_at_its_last_heartbeat(tmp_path):
    last = datetime(2026, 10, 19, 13, 41, 40)  # the last heartbeat
    write(tmp_path, (BOOT, "boot", "", BOOT), *beats(BOOT, BOOT, last))
    later = datetime(2026, 10, 19, 15, 0)
    write(tmp_path, (later, "boot", "", later))
    power = read_power(tmp_path, *DAY, heartbeat_mins=1)
    assert power["on"][0] == ["2026-10-19T07:00:40", last.isoformat(), "unexpected"]


def test_a_gap_in_the_heartbeat_splits_the_running_periods(tmp_path):
    first = beats(BOOT, BOOT, datetime(2026, 10, 19, 8, 0, 40))
    second = beats(BOOT, datetime(2026, 10, 19, 8, 10, 40), datetime(2026, 10, 19, 9, 0, 40))  # 10 min with none
    write(tmp_path, *first, *second)
    assert len(read_power(tmp_path, *DAY, heartbeat_mins=1)["running"]) == 2


def test_the_current_boot_runs_until_now(tmp_path):
    now = datetime.now().replace(microsecond=0)
    boot = now - timedelta(minutes=30)
    write(tmp_path, (boot, "boot", "", boot), *beats(boot, boot, now - timedelta(minutes=1)))
    power = read_power(tmp_path, now - timedelta(hours=1), now + timedelta(hours=1), 1, current_boot=boot)
    assert power["on"][0][2] == "running" and power["on"][0][1] >= (now - timedelta(seconds=1)).isoformat()


@pytest.mark.parametrize("missing", ["folder", "malformed"])
def test_nothing_logged_reads_as_nothing(tmp_path, missing):
    if missing == "malformed":
        (tmp_path / "power").mkdir()
        (tmp_path / "power" / "2026-10-19.csv").write_text(",".join(POWER_HEADERS) + "\nnot,a,row,here\n")
    assert read_power(tmp_path, *DAY, heartbeat_mins=1) == {"on": [], "running": [], "boots": [], "shutdowns": []}


def test_a_late_first_heartbeat_leaves_a_gap_after_the_boot(tmp_path):
    late = BOOT + timedelta(minutes=23)  # the manager wasn't running at first
    write(tmp_path, (late, "boot", "", BOOT), *beats(BOOT, late, late + timedelta(minutes=10)))
    running = read_power(tmp_path, *DAY, heartbeat_mins=1)["running"]
    assert [r[0] for r in running] == ["2026-10-19T07:00:40", late.isoformat()]
