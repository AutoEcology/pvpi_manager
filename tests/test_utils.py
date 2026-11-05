import pytest

from pvpi import utils


@pytest.mark.parametrize(
    "model, has_ttys0, port",
    [
        ("Raspberry Pi 3 Model B Rev 1.2", True, "/dev/ttyS0"),
        ("Raspberry Pi 4 Model B Rev 1.5", True, "/dev/ttyS0"),
        ("Raspberry Pi 400 Rev 1.0", True, "/dev/ttyS0"),
        ("Raspberry Pi 4 Model B Rev 1.5", False, "/dev/ttyAMA0"),  # dtoverlay=disable-bt
        ("Raspberry Pi Zero 2 W Rev 1.0", True, "/dev/ttyS0"),
        ("Raspberry Pi 5 Model B Rev 1.0", True, "/dev/ttyAMA0"),
    ],
)
def test_default_uart_port(tmp_path, monkeypatch, model, has_ttys0, port):
    path = tmp_path / "model"
    path.write_text(model + "\0")
    monkeypatch.setattr(utils, "_MODEL_PATH", str(path))
    monkeypatch.setattr(utils.os.path, "exists", lambda p: has_ttys0)
    utils.default_uart_port.cache_clear()
    assert utils.default_uart_port() == port
    utils.default_uart_port.cache_clear()
