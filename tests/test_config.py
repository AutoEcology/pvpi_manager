import json

from pvpi.config import PvPiConfig


def test_a_missing_config_file_is_made_with_the_defaults(tmp_path):
    path = tmp_path / "pvpi" / "config.json"
    config = PvPiConfig.from_file(str(path))
    assert isinstance(config, PvPiConfig) and config.low_bat_volt == 12.9
    assert json.loads(path.read_text())["low_bat_volt"] == 12.9


def test_a_saved_config_reads_back(tmp_path):
    path = tmp_path / "config.json"
    PvPiConfig(low_bat_volt=12.5, uart_port="/dev/ttyAMA0").save(path)
    saved = json.loads(path.read_text())
    assert saved["shutdown_time"] == "22:00:00" and saved["uart_port"] == "/dev/ttyAMA0"
    assert PvPiConfig.from_file(str(path)).low_bat_volt == 12.5
    assert not list(tmp_path.glob(".*.tmp"))
