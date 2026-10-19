"""The CLI's commands, with a fake board: what each one sends."""

import pytest
from click.testing import CliRunner

from pvpi import cli
from pvpi.client import PvPiClient


REPLIES = {
    b"GET_ALIVE": "ALIVE",
    b"GET_VERSION": "VERSION,PVPi,D,1.15",
    b"GET_TIME": "GET_TIME,26,10,19,11,0,0",
    b"GET_CHARGE_STATE": "CHARGE_STATE,3",
    b"GET_FAULT_CODE": "FAULT_CODE,0",
    b"GET_BAT_V": "MILLIVOLTS,13200",
    b"GET_BAT_C": "MILLIAMPS,500",
    b"GET_PV_V": "MILLIVOLTS,18000",
    b"GET_PV_C": "MILLIAMPS,1200",
    b"GET_TEMP": "TEMP,25",
}


class Board:
    def __init__(self):
        self.sent = []

    def write(self, message):
        self.sent.append(message)
        return REPLIES.get(message, "SET,OK")

    def close(self):
        pass


@pytest.fixture
def invoke(monkeypatch):
    board = Board()
    monkeypatch.setattr(cli, "PvPiClient", lambda: PvPiClient(interface=board))

    def go(*args):
        result = CliRunner().invoke(cli.cli, list(args))
        go.sent = board.sent
        return result

    return go


@pytest.mark.parametrize(
    "command, sent",
    [("set-charge-current", b"SET_CHARGE_MILLIAMPS,500"), ("set-input-current", b"SET_INPUT_MILLIAMPS,500")],
)
def test_currents_take_decimals(invoke, command, sent):
    assert invoke(command, "--current", "0.5").exit_code == 0
    assert invoke.sent == [sent]


@pytest.mark.parametrize(
    "command, request_",
    [("set-mppt", b"SET_MPPT_STATE"), ("set-charging", b"SET_CHARGE_STATE"), ("set-ts", b"SET_TS_STATE")],
)
def test_on_off_commands_need_a_choice(invoke, command, request_):
    assert invoke(command).exit_code != 0 and invoke.sent == []  # no flag: nothing changes
    assert invoke(command, "--enable").exit_code == 0
    assert invoke(command, "--disable").exit_code == 0
    assert invoke.sent == [request_ + b",ON", request_ + b",OFF"]


def test_connection_test_says_it_resets_the_board_before_it_does(invoke):
    assert "default settings" in invoke("connection-test", "--help").output
    result = invoke("connection-test")
    assert result.exit_code == 0, result.output
    assert "default settings" in result.output
    sets = [m for m in invoke.sent if m.startswith(b"SET_")]
    assert sets[0].startswith(b"SET_TIME") and b"SET_WAKEUP_MILLIVOLT,13000" in sets


def test_schedule_shows_the_next_on_periods(tmp_path):
    from pvpi.config import PvPiConfig
    from pvpi.schedule import Schedule

    config = tmp_path / "config.json"
    PvPiConfig(schedule="day").save(config)
    Schedule.model_validate({"rules": [{"kind": "daily", "on": "07:00", "off": "19:00"}]}).save(
        tmp_path / "schedules" / "day.json"
    )
    result = CliRunner().invoke(cli.cli, ["schedule", "--config", str(config)])
    assert result.exit_code == 0, result.output
    assert "07:00:00 to" in result.output and "wake alarm" in result.output
