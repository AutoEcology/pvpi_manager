"""The CLI's commands, with a fake board: what each one sends."""

import pytest
from click.testing import CliRunner

from pvpi import cli
from pvpi.client import PvPiClient


class Board:
    def __init__(self):
        self.sent = []

    def write(self, message):
        self.sent.append(message)
        return "SET,OK"

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
