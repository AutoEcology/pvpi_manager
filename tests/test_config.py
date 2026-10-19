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
    assert saved["schedule"] is None and saved["uart_port"] == "/dev/ttyAMA0"
    assert PvPiConfig.from_file(str(path)).low_bat_volt == 12.5
    assert not list(tmp_path.glob(".*.tmp"))


def test_settings_the_board_would_refuse_are_refused_here():
    import pytest
    from pydantic import ValidationError

    PvPiConfig()  # the defaults fit
    for bad in (
        {"power_off_delay": 0},  # power_off takes 1 to 60 s: a shutdown would never happen
        {"wake_up_volt": 15},
        {"watchdog_period_mins": 61},
        {"keep_for_days": 0},
        {"low_bat_volt": 13.3, "wake_up_volt": 13.2},  # it would wake into another shutdown
    ):
        with pytest.raises(ValidationError):
            PvPiConfig(**bad)


def test_the_replaced_schedule_options_are_refused_naming_the_new_one(tmp_path):
    import pytest
    from pydantic import ValidationError

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"schedule_time": True, "shutdown_time": "19:00:00", "wakeup_time": "07:00:00"}))
    with pytest.raises(ValidationError, match="schedule_time, shutdown_time, wakeup_time: replaced by schedule"):
        PvPiConfig.from_file(str(path))


def test_schedules_are_next_to_the_config_and_an_unworkable_one_is_refused(tmp_path):
    import pytest

    from pvpi.schedule import Schedule

    config = PvPiConfig.from_file(str(tmp_path / "config.json"))
    assert config.schedules_folder == tmp_path / "schedules"
    assert config.load_schedule().always_on  # none chosen
    Schedule.model_validate({"rules": [{"kind": "periodic", "on_for_mins": 5, "off_for_mins": 0.5}]}).save(
        config.schedule_path("short")
    )
    config.schedule = "short"
    with pytest.raises(ValueError, match="Schedule 'short'"):
        config.load_schedule()
    config.schedule = "missing"
    with pytest.raises(FileNotFoundError):
        config.load_schedule()
