import json
import os
import pathlib
from datetime import time
from pathlib import Path

from platformdirs import user_data_dir
from pydantic import Field, model_validator
from pydantic_settings import (
    BaseSettings,
)

from pvpi.utils import default_uart_port


class PvPiConfig(BaseSettings, extra="forbid"):
    uart_port: str = Field(default_factory=default_uart_port, description="UART port path")

    log_period: int = Field(5, description="Pv Pi system metrics logging interval minutes", gt=0)  # mins
    startup_delay: int = Field(20, description="Seconds delay after service start before proceeding", ge=0)  # secs

    low_bat_volt: float = Field(12.9, description="Voltage at which to shutdown the Raspberry Pi", ge=0)  # volts
    low_bat_readings: int = Field(
        3, description="Low battery readings in a row (one every 10 s) before shutting down", ge=1
    )
    wake_up_volt: float = Field(
        13.2, description="Voltage at which power supply will be turned on (11.5 to 14.4)", ge=11.5, le=14.4
    )  # volts

    # Turning the power supply off on shutdown
    power_off_on_shutdown: bool = Field(True, description="Turn off power supply on shutdown")
    power_off_delay: int = Field(
        20, description="Seconds delay after shutdown to turn off power supply (1 to 60)", ge=1, le=60
    )

    # Wakeup & Shutdown times
    schedule_time: bool = Field(False, description="Enable scheduled shutdown and wakeup")
    shutdown_time: time = time(22, 0)  # TODO
    wakeup_time: time = time(8, 0)  # TODO

    # Enable CSV logging of voltages, currents, and temperatures
    log_pvpi_stats: bool = Field(True, description="Enable CSV logging of Pv Pi metrics")
    data_log_path: Path = Field(
        default_factory=lambda: Path(user_data_dir("pvpi")), description="Pv Pi CSV log file path"
    )
    keep_for_days: int = Field(7, description="Num of days logging to retain", ge=1)

    # Watchdog
    enable_watchdog: bool = Field(False, description="Enable power watchdog")
    watchdog_period_mins: int = Field(2, description="Watchdog inspection interval in minutes (1 to 60)", ge=1, le=60)

    # Clocks
    time_pi2mcu: bool = Field(False, description="Set Pv Pi's MCU clock to match Raspberry Pi's clock on boot")
    time_mcu2pi: bool = Field(False, description="Set Raspberry Pi's clock to match Pv Pi's MCU clock on boot")

    # Dashboard
    full_dashboard: bool = Field(True, description="Plot out historical data as well as live stats")

    @model_validator(mode="after")
    def _wakes_above_shutdown(self):
        # Waking at or below the shutdown voltage would shut the Pi down again as it starts.
        if self.wake_up_volt <= self.low_bat_volt:
            raise ValueError(f"wake_up_volt ({self.wake_up_volt}) must be above low_bat_volt ({self.low_bat_volt})")
        return self

    @classmethod
    def from_file(cls, path: str | None = None):
        if path is None:
            return cls()
        ext = pathlib.Path(path).suffix
        if ext == ".json":
            config_path = Path(path)
            if config_path.exists():
                with open(path) as f:
                    return cls.model_validate(json.load(f))
            else:
                config = cls()
                config.save(config_path)
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
