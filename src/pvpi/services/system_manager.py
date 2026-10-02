import logging
import os
import time
from datetime import datetime, timedelta

from pvpi.client import PvPiClient
from pvpi.config import PvPiConfig
from pvpi.logging_ import RotatingCSVLogger
from pvpi.transports import ZmqSerialProxyInterface
from pvpi.utils import set_system_time

_logger = logging.getLogger(__name__)


LOOP_SECS = 10  # between passes of the management loop
MAX_FAILED_PASSES = 5  # passes in a row that can't read the board before the service exits


def _in_shutdown_window(config: PvPiConfig, now: datetime) -> bool:
    shutdown, wakeup = config.shutdown_time, config.wakeup_time
    if shutdown < wakeup:
        # Same day: shutdown window is between shutdown_time and wakeup_time
        return shutdown <= now.time() < wakeup
    # Overnight: e.g. shutdown=23:00, wakeup=06:00
    return now.time() >= shutdown or now.time() < wakeup


def _log_stats(client: PvPiClient, bat_v: float, stats_data_logger: RotatingCSVLogger | None) -> None:
    is_alive = client.get_alive()
    mcu_time = client.get_mcu_time()
    _logger.info("Alive: %s", is_alive)
    _logger.info("Current MCU time: %s", mcu_time)
    _logger.info("System time: %s", datetime.now().strftime("%y-%m-%d %H:%M:%S"))

    bat_c = client.get_battery_current()
    pv_v = client.get_pv_voltage()
    pv_c = client.get_pv_current()
    temperature = client.get_board_temp()
    _logger.info("Battery: %s V, %s A", bat_v, bat_c)
    _logger.info("PV: %s V, %s A", pv_v, pv_c)
    _logger.info("PV PI Temp: %sC", temperature)
    if stats_data_logger:
        stats_data_logger.log_stats(bat_v, bat_c, pv_v, pv_c, temperature)


def run(config: PvPiConfig):
    serial_interface = ZmqSerialProxyInterface()
    client = PvPiClient(interface=serial_interface)

    # Check Pv Pi status
    is_alive = client.get_alive()
    _logger.info("Alive: %s", is_alive)

    # Set one clock to match the other
    if config.time_mcu2pi:
        mcu_time: datetime = client.get_mcu_time()
        set_system_time(mcu_time)
    if config.time_pi2mcu:
        client.set_mcu_time()

    # Setup CSV logger
    stats_data_logger: RotatingCSVLogger | None = None
    if config.log_pvpi_stats:
        _logger.info("Logging PV PI statistics to %s", config.data_log_path)
        stats_data_logger = RotatingCSVLogger(config.data_log_path, config.keep_for_days)

    # Delay start
    if config.startup_delay:
        _logger.info("%is Startup delay", config.startup_delay)
        time.sleep(config.startup_delay)

    _logger.info("Log period: %i minutes", config.log_period)
    _logger.info("Time Schedule: %s", "On" if config.schedule_time else "Off")

    # Setup power watchdog
    _logger.info("Watchdog: %s", "On" if config.enable_watchdog else "Off")
    if config.enable_watchdog:
        client.set_watchdog(config.watchdog_period_mins)
        # Make sure watchdog is reset twice every watchdog period
        watchdog_period_sec = (config.watchdog_period_mins * 60)//2
        prev_watchdog_time = datetime.now() - timedelta(seconds=watchdog_period_sec)
        _logger.info("Watchdog polling interval set to %s min", config.watchdog_period_mins)
    else:
        client.stop_watchdog()

    client.set_wakeup_voltage(config.wake_up_volt)
    _logger.info("Wakeup Voltage set at: %sV", config.wake_up_volt)

    # Pv Pi Logging loop
    log_period_sec = config.log_period * 60
    prev_log_time = datetime.now() - timedelta(seconds=log_period_sec)

    low_readings = 0  # low battery readings in a row
    failed_passes = 0  # passes in a row that couldn't read the board
    try:
        while True:
            curr_time = datetime.now()
            if config.schedule_time and _in_shutdown_window(config, curr_time):
                _logger.info("Shutdown Time!")
                break

            try:
                if config.enable_watchdog:
                    sec_since_last_wd = (curr_time - prev_watchdog_time).seconds
                    if sec_since_last_wd >= watchdog_period_sec:
                        is_alive = client.get_alive()
                        _logger.info("Watchdog Alive: %s", is_alive)
                        prev_watchdog_time = datetime.now()

                bat_v = client.get_battery_voltage()  # every pass, for the low battery check

                sec_since_last_log = (curr_time - prev_log_time).seconds
                if sec_since_last_log >= log_period_sec:
                    prev_log_time = datetime.now()
                    _log_stats(client, bat_v, stats_data_logger)
            except Exception as err:
                # One bad or late reply: try again next pass, and give up (so systemd starts
                # the service again) only when the board keeps failing.
                failed_passes += 1
                _logger.warning("Couldn't read the PV PI (%i in a row): %s", failed_passes, err)
                if failed_passes >= MAX_FAILED_PASSES:
                    raise
                time.sleep(LOOP_SECS)
                continue
            failed_passes = 0

            # Shut down only after several low readings in a row, so a short load spike
            # (a camera or modem starting) doesn't power the device off.
            if bat_v <= config.low_bat_volt:
                low_readings += 1
                _logger.info("Battery low: %s V (%i of %i)", bat_v, low_readings, config.low_bat_readings)
                if low_readings >= config.low_bat_readings:
                    _logger.info("Shutdown Voltage!")
                    break
            else:
                low_readings = 0

            time.sleep(LOOP_SECS)
    except Exception:
        # The watchdog is left as it is: with it on, the PV PI still restarts a Pi whose
        # manager stays down.
        serial_interface.close()
        raise
    else:
        _logger.info("Closing down...")
        client.stop_watchdog()
        _logger.info("Watchdog stopped")

        if config.schedule_time:
            client.set_alarm(config.wakeup_time)
            _logger.info("Alarm set %s", config.wakeup_time)
        if config.power_off_on_shutdown:
            client.power_off(delay_s=config.power_off_delay)
            _logger.info("Powering off Pv Pi")

        _logger.info("Shutting down...")
        time.sleep(1)
        os.system("sudo shutdown now")  # warning: requires permissions
        while True:
            _logger.info("sleeping, waiting for shutdown...")
            time.sleep(100)
