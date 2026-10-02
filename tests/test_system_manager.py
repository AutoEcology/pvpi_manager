"""The manager's loop, with a fake board: when it shuts down, and what a bad reading does."""

import pytest

from pvpi.config import PvPiConfig
from pvpi.services import system_manager


class Shutdown(Exception):
    pass


class FakeBoard:
    def __init__(self, voltages):
        self.voltages = list(voltages)  # each pass's battery reading; an Exception to fail it
        self.calls = []

    def __getattr__(self, name):  # every other request: answered, and noted
        return lambda *a, **k: self.calls.append(name) or 1

    def get_battery_voltage(self):
        value = self.voltages.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


@pytest.fixture
def run(monkeypatch, tmp_path):
    def go(voltages, **settings):
        board = go.board = FakeBoard(voltages)
        monkeypatch.setattr(system_manager, "ZmqSerialProxyInterface", lambda: type("I", (), {"close": lambda s: None})())
        monkeypatch.setattr(system_manager, "PvPiClient", lambda interface: board)
        monkeypatch.setattr(system_manager.time, "sleep", lambda s: None)

        def shutdown(cmd):
            raise Shutdown(cmd)

        monkeypatch.setattr(system_manager.os, "system", shutdown)
        config = PvPiConfig(startup_delay=0, log_pvpi_stats=False, data_log_path=tmp_path, **settings)
        system_manager.run(config)

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
