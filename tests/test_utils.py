import pytest

from pvpi import utils


@pytest.mark.parametrize(
    "model, serial0, port",
    [
        ("Raspberry Pi 3 Model B Rev 1.2", "/dev/ttyS0", "/dev/ttyS0"),  # Bluetooth on the PL011
        ("Raspberry Pi 3 Model A Plus Rev 1.0", "/dev/ttyAMA0", "/dev/ttyAMA0"),  # dtoverlay=disable-bt
        ("Raspberry Pi 4 Model B Rev 1.5", "/dev/ttyAMA0", "/dev/ttyAMA0"),
        ("Raspberry Pi Zero 2 W Rev 1.0", "/dev/ttyS0", "/dev/ttyS0"),
        ("Raspberry Pi 5 Model B Rev 1.0", "/dev/ttyAMA10", "/dev/ttyAMA0"),  # serial0 is the debug header
        ("Raspberry Pi 500 Rev 1.0", "/dev/ttyAMA10", "/dev/ttyAMA0"),
        ("Raspberry Pi 4 Model B Rev 1.5", None, "/dev/ttyS0"),  # no serial0: not Raspberry Pi OS
        ("Raspberry Pi Zero W Rev 1.1", None, "/dev/ttyS0"),
        ("Raspberry Pi 5 Model B Rev 1.0", None, "/dev/ttyAMA0"),
    ],
)
def test_default_uart_port(tmp_path, monkeypatch, model, serial0, port):
    path = tmp_path / "model"
    path.write_text(model + "\0")
    monkeypatch.setattr(utils, "_MODEL_PATH", str(path))
    monkeypatch.setattr(utils.os.path, "exists", lambda p: serial0 is not None)
    monkeypatch.setattr(utils.os.path, "realpath", lambda p: serial0)
    utils.default_uart_port.cache_clear()
    assert utils.default_uart_port() == port
    utils.default_uart_port.cache_clear()
