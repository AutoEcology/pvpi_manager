import json
import os
import pathlib
from datetime import timedelta
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir
from pydantic import Field, PrivateAttr, model_validator
from pydantic_settings import (
    BaseSettings,
)

from pvpi.schedule import Schedule
from pvpi.utils import default_uart_port

SCHEDULE_NAME = r"^[A-Za-z0-9_-]+$"
_REPLACED = ("schedule_time", "shutdown_time", "wakeup_time")


class PvPiConfig(BaseSettings, extra="forbid"):
    uart_port: str = Field(
        default_factory=default_uart_port, description="The serial port the PV Pi is on (found automatically for Raspberry Pi's)"
    )

    log_period: int = Field(5, description="Minutes between readings in the log", gt=0)  # mins
    startup_delay: int = Field(
        20, description="Seconds the manager waits after starting before it does anything", ge=0
    )  # secs

    low_bat_volt: float = Field(12.9, description="Battery voltage at which the Pi shuts down", ge=0)  # volts
    low_bat_readings: int = Field(
        3, description="How many low readings in a row (one every 10 s) before the Pi shuts down", ge=1
    )
    wake_up_volt: float = Field(
        13.2, description="Battery voltage at which the PV Pi turns the Pi back on (11.5 to 14.4)", ge=11.5, le=14.4
    )  # volts

    # Turning the power supply off on shutdown
    power_off_on_shutdown: bool = Field(True, description="Turn the Pi's power off after it shuts down")
    power_off_delay: int = Field(
        20, description="Seconds between the shutdown and the power going off (1 to 60)", ge=1, le=60
    )

    # The power schedule: a file of on and off times (see pvpi/schedule.py)
    schedule: str | None = Field(
        None, pattern=SCHEDULE_NAME, description="The schedule in use (its file name); empty to stay on all the time"
    )
    schedules_dir: Path | None = Field(
        None, description="Where schedule files are kept; empty for a 'schedules' folder next to this config"
    )

    # Enable CSV logging of voltages, currents, and temperatures
    log_pvpi_stats: bool = Field(True, description="Keep CSV logs of the readings and the power log")
    data_log_path: Path = Field(
        default_factory=lambda: Path(user_data_dir("pvpi")), description="Where the logs are kept"
    )
    keep_for_days: int = Field(7, description="Days of logs to keep", ge=1)
    heartbeat_mins: int = Field(
        1,
        description='Minutes between the manager\'s "still running" entries in the power log (1 to 60)',
        ge=1,
        le=60,
    )

    # Watchdog
    enable_watchdog: bool = Field(False, description="Have the PV Pi restart the Pi if the manager stops answering")
    watchdog_period_mins: int = Field(
        2,
        description="Minutes the PV Pi waits to hear from the manager before restarting the Pi (1 to 60)",
        ge=1,
        le=60,
    )

    # Clocks
    time_pi2mcu: bool = Field(False, description="When the Pi starts, set the PV Pi's clock from the Pi's")
    time_mcu2pi: bool = Field(
        False, description="When the Pi starts, set its clock from the PV Pi's (use this if your Pi isn't connected to a network)"
    )

    # Dashboard
    full_dashboard: bool = Field(
        True, description="Show the history charts on the dashboard, not just the live readings"
    )

    _source: Path | None = PrivateAttr(None)  # the file it was read from

    @model_validator(mode="before")
    @classmethod
    def _refuse_replaced(cls, data):
        if isinstance(data, dict) and (old := [k for k in _REPLACED if k in data]):
            raise ValueError(
                f"{', '.join(old)}: replaced by schedule files. Put the on and off times in a schedule file "
                "in schedules_dir and set schedule to its name (see the README's Scheduling section)"
            )
        return data

    @model_validator(mode="after")
    def _wakes_above_shutdown(self):
        # Waking at or below the shutdown voltage would shut the Pi down again as it starts.
        if self.wake_up_volt <= self.low_bat_volt:
            raise ValueError(f"wake_up_volt ({self.wake_up_volt}) must be above low_bat_volt ({self.low_bat_volt})")
        return self

    @property
    def schedules_folder(self) -> Path:
        if self.schedules_dir is not None:
            return Path(self.schedules_dir)
        if self._source is not None:
            return self._source.parent / "schedules"
        return Path(user_config_dir("pvpi")) / "schedules"

    @property
    def min_on(self) -> timedelta:
        """The shortest on period: time for the Pi to start up and the manager to begin."""
        return timedelta(seconds=self.startup_delay + 60)

    @property
    def min_off(self) -> timedelta:
        """The shortest off period: time for the Pi to shut down and the power to go off before
        the wake alarm."""
        return timedelta(seconds=self.power_off_delay + 60)

    def schedule_path(self, name: str) -> Path:
        return self.schedules_folder / f"{name}.json"

    def check_schedule(self, schedule: Schedule) -> list[str]:
        return schedule.problems(self.min_on, self.min_off)

    def load_schedule(self) -> Schedule:
        """The schedule in use; raises if its file is missing or unworkable."""
        if self.schedule is None:
            return Schedule()
        schedule = Schedule.load(self.schedule_path(self.schedule))
        if problems := self.check_schedule(schedule):
            raise ValueError(f"Schedule '{self.schedule}': " + "; ".join(problems))
        return schedule

    @classmethod
    def from_file(cls, path: str | None = None):
        if path is None:
            return cls()
        ext = pathlib.Path(path).suffix
        if ext == ".json":
            config_path = Path(path)
            if config_path.exists():
                with open(path) as f:
                    config = cls.model_validate(json.load(f))
            else:
                config = cls()
                config.save(config_path)
            config._source = config_path.resolve()
            return config

        raise ValueError(f"unsupported file type '{ext}'")

    def save(self, path: str | Path) -> None:
        """Write this config as JSON to `path`, replacing it in one step, so a service
        starting meanwhile never reads half a file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(json.dumps(self.model_dump(mode="json"), indent=2) + "\n")
        os.replace(tmp, path)
