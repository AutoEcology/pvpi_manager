"""The manager's loop, with a fake board: when it shuts down, and what a bad reading does."""

import os
from datetime import datetime, time, timedelta

import pytest

from pvpi.config import PvPiConfig
from pvpi.schedule import Schedule
from pvpi.services import system_manager

DAY = {"kind": "daily", "on": "07:00", "off": "19:00"}


class Shutdown(Exception):
    pass


class FakeBoard:
    def __init__(self, voltages, failing=()):
        self.voltages = list(voltages)  # each pass's battery reading; an Exception to fail it
        self.failing = failing  # requests that fail
        self.calls = []
        self.args = {}

    def __getattr__(self, name):  # every other request: answered (or failed), and noted
        def request(*a, **k):
            self.calls.append(name)
            self.args[name] = a or tuple(k.values())
            if name in self.failing:
                raise TimeoutError("no reply")
            return 1

        return request

    def get_battery_voltage(self):
        value = self.voltages.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


@pytest.fixture
def run(monkeypatch, tmp_path):
    """run(voltages, rules=None, now=..., on_sleep=None, **settings): the manager on a fake board
    and a clock that moves on 10 s each pass, until it shuts down. `rules`: the schedule in use."""

    def go(voltages, failing=(), rules=None, now=datetime(2026, 10, 19, 12, 0), on_sleep=None, **settings):
        board = go.board = FakeBoard(voltages, failing)
        clock = go.clock = [now]
        monkeypatch.setattr(
            system_manager, "ZmqSerialProxyInterface", lambda: type("I", (), {"close": lambda s: None})()
        )
        monkeypatch.setattr(system_manager, "PvPiClient", lambda interface: board)

        def sleep(secs):
            clock[0] += timedelta(seconds=secs)
            if on_sleep:
                on_sleep()

        monkeypatch.setattr(system_manager.time, "sleep", sleep)
        monkeypatch.setattr(system_manager, "datetime", type("D", (datetime,), {"now": staticmethod(lambda: clock[0])}))

        def shutdown(cmd, check):
            raise Shutdown(" ".join(cmd))

        monkeypatch.setattr(system_manager.subprocess, "run", shutdown)
        path = tmp_path / "config.json"
        if rules is not None:
            Schedule.model_validate({"rules": rules}).save(tmp_path / "schedules" / "test.json")
            settings["schedule"] = "test"
        PvPiConfig(startup_delay=0, log_pvpi_stats=False, data_log_path=tmp_path, **settings).save(path)
        system_manager.run(PvPiConfig.from_file(str(path)))

    go.path = tmp_path / "config.json"
    return go


def test_one_low_reading_doesnt_shut_down_but_several_in_a_row_do(run):
    with pytest.raises(Shutdown, match="shutdown now"):
        run([12.5, 13.1, 12.5, 12.6, 12.7, 12.8], low_bat_volt=12.9, low_bat_readings=3)
    assert run.board.voltages == [12.8]  # it shut down on the 3rd low reading in a row, not the 1st


def test_the_battery_is_checked_every_pass_not_only_when_logging(run):
    with pytest.raises(Shutdown):
        run([12.5, 12.5, 12.5], low_bat_volt=12.9, low_bat_readings=3, log_period=60)
    assert run.board.calls.count("get_pv_voltage") == 1  # three passes, one of them logging


def test_a_bad_reading_is_skipped_and_the_watchdog_left_on_when_it_keeps_failing(run):
    with pytest.raises(Shutdown):
        run([TimeoutError("late"), 13.0, 12.5, 12.5, 12.5], low_bat_volt=12.9)
    assert run.board.voltages == []  # past the failed pass, on to the low readings
    failures = [TimeoutError("late")] * system_manager.MAX_FAILED_PASSES
    with pytest.raises(TimeoutError):
        run(failures, enable_watchdog=True)
    assert "set_watchdog" in run.board.calls and "stop_watchdog" not in run.board.calls


@pytest.mark.parametrize("failing", ["stop_watchdog", "set_alarm", "power_off"])
def test_a_failed_request_on_the_way_down_doesnt_stop_the_shutdown(run, failing):
    with pytest.raises(Shutdown, match="shutdown now"):
        run([13.1] * 3, failing=(failing,), enable_watchdog=True, rules=[DAY], now=datetime(2026, 10, 19, 19, 0, 5))
    assert {"stop_watchdog", "set_alarm", "power_off"} <= set(run.board.calls)


def test_it_shuts_down_when_the_schedule_turns_off_and_sets_the_alarm_for_the_next_on(run):
    with pytest.raises(Shutdown):
        run([13.1] * 10, rules=[DAY], now=datetime(2026, 10, 19, 18, 59, 35))
    assert run.clock[0] >= datetime(2026, 10, 19, 19, 0)  # on until 19:00
    assert run.board.args["set_alarm"] == (time(7, 0),)


def test_with_no_schedule_it_sets_no_alarm(run):
    with pytest.raises(Shutdown):
        run([12.5] * 3, low_bat_volt=12.9)
    assert "set_alarm" not in run.board.calls


def test_it_stays_on_when_the_off_period_left_is_too_short_to_shut_down_in(run):
    cycle = {"kind": "periodic", "on_for_mins": 5, "off_for_mins": 2, "start": "07:00", "end": "08:00"}
    with pytest.raises(Shutdown):
        run([13.1] * 100, rules=[cycle], now=datetime(2026, 10, 19, 7, 6, 15))  # 45 s before 07:07
    assert run.clock[0] >= datetime(2026, 10, 19, 7, 12)  # on through 07:07-07:12, off at 07:12
    assert run.board.args["set_alarm"] == (time(7, 14),)


def test_a_changed_schedule_is_used_without_a_restart(run):
    def choose_a_schedule():
        if run.clock[0] == datetime(2026, 10, 19, 20, 0, 10):  # after the first pass
            Schedule.model_validate({"rules": [DAY]}).save(run.path.parent / "schedules" / "day.json")
            config = PvPiConfig.from_file(str(run.path))
            config.schedule = "day"
            config.save(run.path)
            os.utime(run.path, (1e9, 1e9))  # a modification time it hasn't seen

    with pytest.raises(Shutdown):
        run([13.1] * 10, now=datetime(2026, 10, 19, 20, 0), on_sleep=choose_a_schedule)
    assert run.board.args["set_alarm"] == (time(7, 0),)
