from pvpi.client import PvPiClient


class Board:
    def __init__(self):
        self.sent = []

    def write(self, message):
        self.sent.append(message)
        return "SET,OK"

    def close(self):
        pass


def test_settings_go_to_the_board_in_whole_units():
    board = Board()
    client = PvPiClient(interface=board)
    for set_it in (client.set_wakeup_voltage, client.set_max_charge_current, client.set_max_input_current):
        try:
            set_it(12.9 if set_it == client.set_wakeup_voltage else 1.005)
        except ValueError:
            pass  # only what was sent matters here
    assert board.sent == [b"SET_WAKEUP_MILLIVOLT,12900", b"SET_CHARGE_MILLIAMPS,1005", b"SET_INPUT_MILLIAMPS,1005"]
