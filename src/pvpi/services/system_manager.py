import logging
import subprocess
import time
from datetime import datetime, timedelta

from pvpi.client import PvPiClient
from pvpi.config import PvPiConfig
from pvpi.logging_ import RotatingCSVLogger
from pvpi.power_log import PowerLog
from pvpi.schedule import Schedule
from pvpi.transports import ZmqSerialProxyInterface
from pvpi.utils import set_system_time

_logger = logging.getLogger(__name__)


LOOP_SECS = 10  # between passes of the management loop
MAX_FAILED_PASSES = 5  # passes in a row that can't read the board before the service exits
# A schedule's off periods are at least the config's min_off long; the manager may notice one up
# to two passes late and still shut down in time for the wake alarm.
LATE_MARGIN = timedelta(seconds=2 * LOOP_SECS)


class _ScheduleWatch:
    """The schedule in use, read again when it's changed (e.g. from the dashboard): a new
    schedule file, or the config choosing another one. Other config changes need a restart."""

    def __init__(self, config: PvPiConfig):
        self.config = config
        self.schedule = config.load_schedule()  # an unworkable schedule stops the service here
        self._seen = self._stamp()
        _logger.info("Schedule: %s", config.schedule or "none, always on")

    def _stamp(self) -> tuple:
        paths = [self.config._source]
        if self.config.schedule is not None:
            paths.append(self.config.schedule_path(self.config.schedule))
        return tuple(_mtime(p) for p in paths)

    def get(self) -> Schedule:
        if self._stamp() != self._seen:
            try:
                config = PvPiConfig.from_file(str(self.config._source)) if self.config._source else self.config
                self.schedule, self.config = config.load_schedule(), config
                _logger.info("Schedule changed: %s", config.schedule or "none, always on")
            except Exception as err:
                _logger.error("Keeping the schedule in use; the changed one can't be used: %s", err)
            self._seen = self._stamp()
        return self.schedule


def _mtime(path) -> float | None:
    try:
        return path.stat().st_mtime if path else None
    except OSError:
        return None


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

    # The power log: this boot, the manager's heartbeat, and the shutdown. Started after the
    # delay, so a clock set from the network by then is used for the boot time.
    power_log: PowerLog | None = None
    if config.log_pvpi_stats:
        power_log = PowerLog(config.data_log_path, config.keep_for_days, config.heartbeat_mins)
        power_log.started()

    _logger.info("Log period: %i minutes", config.log_period)
    watch = _ScheduleWatch(config)

    # Setup power watchdog
    _logger.info("Watchdog: %s", "On" if config.enable_watchdog else "Off")
    if config.enable_watchdog:
        client.set_watchdog(config.watchdog_period_mins)
        # Make sure watchdog is reset twice every watchdog period
        watchdog_period_sec = (config.watchdog_period_mins * 60) // 2
        prev_watchdog_time = datetime.now() - timedelta(seconds=watchdog_period_sec)
        _logger.info("Watchdog polling interval set to %s min", config.watchdog_period_mins)
    else:
        client.stop_watchdog()

    client.set_wakeup_voltage(config.wake_up_volt)
    _logger.info("Wakeup Voltage set at: %sV", config.wake_up_volt)

    # Pv Pi Logging loop
    log_period_sec = config.log_period * 60
    prev_log_time = datetime.now() - timedelta(seconds=log_period_sec)

    staying_on_logged = False
    low_readings = 0  # low battery readings in a row
    failed_passes = 0  # passes in a row that couldn't read the board
    try:
        while True:
            curr_time = datetime.now()
            if power_log:
                power_log.beat()
            schedule = watch.get()
            if not schedule.is_on(curr_time):
                wake = schedule.next_on(curr_time)
                if wake is None or wake - curr_time >= watch.config.min_off - LATE_MARGIN:
                    _logger.info("Shutdown Time!")
                    reason = "schedule"
                    break
                # Too close to the next on time to shut down and still wake for it.
                if not staying_on_logged:
                    _logger.info("Off until %s, too soon to shut down: staying on", wake)
                    staying_on_logged = True
            else:
                staying_on_logged = False

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
                    reason = "low battery"
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
        if power_log:
            _attempt("log the shutdown", power_log.shutdown, reason)
        # A failed request is logged and the shutdown goes ahead: on a low battery the Pi
        # must still shut down.
        if _attempt("stop the watchdog", client.stop_watchdog):
            _logger.info("Watchdog stopped")
        alarm = watch.get().alarm(datetime.now() + watch.config.min_off - LATE_MARGIN)
        if alarm is not None and _attempt("set the wake alarm", client.set_alarm, alarm.time()):
            _logger.info("Alarm set %s", alarm)
        if config.power_off_on_shutdown and _attempt(
            "schedule the power off", client.power_off, delay_s=config.power_off_delay
        ):
            _logger.info("Powering off Pv Pi")

        _logger.info("Shutting down...")
        time.sleep(1)
        done = subprocess.run(["sudo", "-n", "shutdown", "now"], check=False)  # needs passwordless sudo
        if done.returncode != 0:
            raise RuntimeError(f"'sudo -n shutdown now' failed ({done.returncode}): is passwordless sudo set up?")
        while True:
            _logger.info("sleeping, waiting for shutdown...")
            time.sleep(100)


def _attempt(what: str, request, *args, **kwargs) -> bool:
    """Make one request to the board; log it and return False if it fails."""
    try:
        request(*args, **kwargs)
        return True
    except Exception:
        _logger.exception("Couldn't %s", what)
        return False
