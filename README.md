# pvpi_manager
The official Python SDK for the PV Pi.<br>
The PV Pi or the PhotoVoltaic Pi is the first Raspberry Pi HAT that can provide power
from a high-capacity 12 Volt lithium-ion phosphate battery (LiFePO4) while also charg-
ing that battery from a large solar panel. The PV Pi with its onboard microcontroller
also enables a range of smart features to support off-grid operation of your Raspberry
Pi in remote locations.

# Support and Documentation
For more information on the PV Pi you can consult the [User Manual](https://static1.squarespace.com/static/6767a8ab1279321b70138597/t/69dae05a35751f0597eea13b/1775951962539/PV_PI_User_Manual.pdf) <br>
For help setting up your device you can watch the [PV Pi Tutorials](https://youtube.com/playlist?list=PLbFaSy7wJeFz2h7MJX0VhsMdpvZVvqfuv&si=jxs1IlyUbiJkMmiR) on the AutoEcology Youtube channel <br>
For questions and comments head over to the [AutoEcology Discord Server](https://discord.gg/jhXaSxVU9g)<br>

# Setup
## Requirements
PV PI Manager is designed to operate on Raspberry Pi compatible devices.  
The following setup was verified on a Raspberry Pi 5 with Raspberry Pi OS (64-bit) (Release: 2025-12-04).

### Python `uv`

Python packager manager [uv](https://docs.astral.sh/uv) is the preferred method for operating the PVPI.
```shell
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Enabling UART
The PV PI communicates over the UART port. By default, the Raspberry Pi does not have this port enabled. Enable the UART port by:
1. `sudo raspi-config`
2. Select `3 Interface Options`
3. Select `I6 Serial Port`
4. Select "No" to "Would you like a login shell to be accessible over serial"
5. Select "Yes" to "Would you like the serial port hardware to be enabled."
6. Exit setup & reboot device.

For the Raspberry Pi and other SBC using the 40pin header the PV PI will use the UART port on pins GPIO 14/15. The PV PI manager auto-detects the board model and selects the correct default port:
- Raspberry Pi (standard models): `/dev/ttyAMA0`
- Raspberry Pi Zero variants: `/dev/ttyS0`

On a Raspberry Pi 5 the same can be done by adding `dtparam=uart0=on` to `/boot/firmware/config.txt` and rebooting, which gives `/dev/ttyAMA0` on GPIO 14/15.
On a Raspberry Pi 3 or 4, `/dev/ttyAMA0` is used by Bluetooth unless `dtoverlay=disable-bt` is in `/boot/firmware/config.txt`; otherwise set `uart_port` to `/dev/ttyS0`.

You can override the port by setting `uart_port` in the `config.json` file.

### Disable Sudo Password
As of version 6.2 of Raspberry Pi OS, passwordless sudo is now disabled by default.
The PV Pi manager requires sudo for shutdown commands (and for setting the Pi's clock when `time_mcu2pi` is on), which will currently fail if you don't enable passwordless sudo.
1. `sudo raspi-config`
2. Select `1 System Options`
3. Select `S10 Admin Password`
4. Select "No" to "Would you like admin (sudo) password to be enabled"
   
## Installation

Clone the repo:
```shell
git clone https://github.com/AutoEcology/pvpi_manager.git
cd pvpi_manager
uv sync
uv run pvpi
```

To update later:
```shell
git pull
uv sync
uv run pvpi restart
```

If you're updating from an older version whose dashboard ran as root, `uv sync` may stop with "Permission denied" on a `__pycache__` folder. Give the files back to your user once, then sync again:
```shell
sudo chown -R $USER: .venv
```

# Quick-start

```shell
cd pvpi_manager
uv run pvpi  # show usage help

uv run pvpi connection-test
```

`connection-test` checks the connection and reports the PV Pi's readings. It also resets the PV Pi to its default settings: its clock from the Pi's clock, MPPT on, charging on, battery temperature monitoring off, 10 A maximum charge current and a 13 V wake-up voltage. The manager service sets the wake-up voltage back to the config's `wake_up_volt` when it next starts.

## Install PV Pi Manager Service

PV Pi manager comes with an `install` command to setup an automatic PV Pi Manager Service that will handle power management and scheduling. 

```shell
uv run pvpi install
```

The installation places two system services that will run automatically upon every boot, three if you add the dashboard. They run the `pvpi` of the environment `install` was run from (e.g. `pvpi_manager/.venv/bin/pvpi`), with nothing in front of it. There is:
- The UART Proxy is a service that manages communications to the PV PI for multiple applications attempting to do so at once. It holds onto the serial connection to the PV Pi and proxies requests over a local socket (`tcp://127.0.0.1:5555`, reachable only from the Pi itself).
- The Manager services is a simple looping script that communicates, via the UART proxy, to the PV Pi and logs metrics. Every 10 seconds it checks the battery, and it shuts the Pi down once `low_bat_readings` readings in a row (3 by default) are at or below `low_bat_volt`, so a short dip under load doesn't power the device off. A reading that fails is retried on the next pass; the service only stops (and systemd starts it again) after 5 failed passes in a row.
- The Dashboard (optional) is a small web page showing live PV Pi readings and charts of the logged history, on port 8501, with a page to create and choose power schedules (see Scheduling). The history needs `log_pvpi_stats` to be enabled. The dashboard has no login: anyone who can reach port 8501 can change the schedule.

### Want the dashboard too?
The dashboard is off unless you ask for it. To add it:

```shell
uv run pvpi install --dashboard
```

Then open `http://<your-pi>:8501` in a browser on the same network (e.g. `http://raspberrypi.local:8501`). It's light enough to run alongside your own programs, even on a Pi Zero.

Changed your mind? Take it off again with:

```shell
uv run pvpi install --no-dashboard
```

Running `pvpi install` again (e.g. after an update) leaves the dashboard as you set it up, and keeps a service you've disabled (`sudo systemctl disable --now pvpi_dashboard.service`) disabled.

This is an optional installation. Each service can be run directly via the CLI (`uv run pvpi dashboard` starts the dashboard until you stop it), and none are required to run in order to use the PV Pi SDK. They serve as examples on which to base your own work.

# Scheduling
A power schedule sets the times the Pi is on. Outside them, the PV Pi Manager service shuts the Pi down and sets the PV Pi's wake alarm, so the Pi starts again at the next on time. With no schedule in use, the Pi is always on (and only shuts down on a low battery).

Each schedule is a JSON file of rules in a `schedules` folder next to the config file (`schedules_dir` in the config picks another folder). The Pi is on whenever any rule is on. There are two kinds of rule:
- `daily`: on from one time of day to another (into the next day if `off` is earlier than `on`).
- `periodic`: on and off in turn, e.g. 5 minutes on then 5 off, between `start` and `end` (all day when they're the same, the default). The cycle begins at `start` each day.

Both take `days`, the days a rule starts on (every day by default). For example, `schedules/field.json`:
```json
{"rules": [
  {"kind": "daily", "on": "07:00", "off": "12:00", "days": ["mon", "tue", "wed", "thu", "fri"]},
  {"kind": "periodic", "on_for_mins": 5, "off_for_mins": 5, "start": "12:00", "end": "19:00"}
]}
```

The repo's `schedules` folder comes with demo schedules to use as they are or as a starting point: `daytime`, `weekdays_office_hours`, `dawn_and_dusk`, `night_only`, `every_10_minutes` and `daytime_duty_cycle`.

Set `schedule` in the config to the file's name (`"schedule": "field"`) to use it. The manager picks up a new or changed schedule within 10 seconds, with no restart. A schedule is refused if it has an on period too short for the Pi to start up (`startup_delay` + 60 s) or an off period too short for it to shut down and the power to go off (`power_off_delay` + 60 s).

The schedule uses the Pi's clock. In the field, with no network, enable `time_mcu2pi` so the Pi takes its time from the PV Pi's clock when it starts, and set that clock once with `pvpi set-mcu-clock`.

The dashboard's Schedule page creates, checks and chooses schedules. To see a schedule's next 24 hours from the command line:
```shell
uv run pvpi schedule          # the schedule in use
uv run pvpi schedule field    # another schedule file
```

Older configs with `schedule_time`, `shutdown_time` and `wakeup_time` are refused: move those times into a schedule file (a `daily` rule with `on` set to the old `wakeup_time` and `off` to the old `shutdown_time`).

# The power log
With `log_pvpi_stats` on, the manager also keeps a power log: one CSV a day in a `power` folder inside `data_log_path`, kept for `keep_for_days` like the readings. Each row has a `Timestamp`, an `Event`, a `Reason` and the `Boot time` it belongs to. The events are:
- `boot`: the Pi started (logged once per boot, also if the manager restarts);
- `running`: the manager's heartbeat, every `heartbeat_mins` minutes (1 by default), showing when it was running;
- `shutdown`: the manager shut the Pi down, with the reason `schedule` or `low battery`.

A boot with no `shutdown` ended unexpectedly (the power was lost, or the Pi crashed) after its last heartbeat. The dashboard's Power chart, at the bottom of the readings page, shows when the Pi was on and the manager running, with a mark at each boot and shutdown.

# Other CLI commands

## Setting PV Pi STM32 RTC clock time
The PV Pi's RTC can receive a "set clock" command using the SDK. You'll only need to do this once if you have a RTC backup battery connected to the PV Pi. If you don't have a RTC backup battery then the RTC will loose time whenever the main battery power is disconnected.  

The following command will set the Pv Pi clock to match the system time of the machine calling the command (give or take a second or so).

```shell
uv run pvpi set-mcu-clock
```

## Restart PV Pi Systemd services
Restarts both the Pv Pi Manager & UART proxy systemd service.
```shell
uv run pvpi restart
```

## Get the PV Pi Battery/Solar Statistics
Prints out the current PV Pi temperature as well as Battery and Solar voltage and charge current.

```shell
uv run pvpi get-stats
```

## Get the BQ25756 charging State
Prints out the current state of the BQ25756 charge cycle.

```shell
uv run pvpi get-charge-state
```

## Get PV Pi Fault States
Prints out the description of any current faults of the PV Pi/BQ25756.

```shell
uv run pvpi get-faults
```

## Set PV Pi Charge Current
Set the maximum battery charge current for the PV Pi, from 0.4 to 10 amps.

```shell
uv run pvpi set-charge-current --current 5
uv run pvpi set-charge-current --current 0.5
```

## Set PV Pi Input Current
Set the maximum input current for the PV Pi, from 0.4 to 8 amps.

```shell
uv run pvpi set-input-current --current 2
```

## Set PV Pi MPPT State
Enable or disable the PV Pi's MPPT. One of `--enable` or `--disable` is required.
```shell
uv run pvpi set-mppt --enable
uv run pvpi set-mppt --disable
```

## Set TS State
Enable or disable the BQ25756's battery temperature monitoring. One of `--enable` or `--disable` is required.
```shell
uv run pvpi set-ts --enable
uv run pvpi set-ts --disable
```

## Set PV Pi Charging State
Enable or disable PV Pi battery charging. One of `--enable` or `--disable` is required.
```shell
uv run pvpi set-charging --enable
uv run pvpi set-charging --disable
```


# More about systemd

(i) `systemd` is the standard system and service manager for modern Linux distributions. Once installed, you can check the `status`, `start`, `stop`, or `restart` these PV PI services using the `systemctl` command:
```shell
sudo systemctl status pvpi_manager.service
sudo systemctl status pvpi_uart.service
sudo systemctl status pvpi_dashboard.service  # if you added the dashboard
```

For example, to stop and disable the dashboard so it will no longer run on boot:
```shell
sudo systemctl stop pvpi_dashboard.service
sudo systemctl disable pvpi_dashboard.service
```

While the status of services can be viewed with `systemctl` as shown above, the log output can be followed using `journalctl`.

To follow the **live** log output from any service:
```shell
journalctl -u pvpi_manager.service -f
journalctl -u pvpi_uart.service -f
journalctl -u pvpi_dashboard.service -f  # if you added the dashboard
```

(i) `journalctl` is a Linux command-line tool for viewing and managing logs from `systemd`. Logs can be filtered by process and time. [Learn more](https://www.digitalocean.com/community/tutorials/how-to-use-journalctl-to-view-and-manipulate-systemd-logs).

# Updating the PV Pi Manager config
When you install the PV Pi Manager service a default config.json file will be created: in the pvpi_manager directory for a cloned repo, or in `~/.config/pvpi/` for a package installed with pip (`pvpi install --config <file>` picks another place). Subsequent restarts of the PV Pi Manager services will load configuration parameters from this config.json. To see which file the installed services use:
```shell
uv run pvpi config-path
```

Settings the PV Pi wouldn't accept are refused when the config is loaded, e.g. `wake_up_volt` must be between 11.5 and 14.4 V and above `low_bat_volt`, and `power_off_delay` between 1 and 60 seconds.

You can change the behaviour of the PV Pi Manager services by editing and saving this file and restarting the PV Pi Manager services.
```shell
uv run pvpi restart
```

# Adding the pvpi client to your own project!
You can use uv or pip to add the pvpi client to your Python project.
```shell
uv add pvpi
```
OR
```shell
pip install pvpi
```

A pip-installed `pvpi install` sets up the services from that environment too.

## Creating your own client node

```python
from pvpi import PvPiClient

client = PvPiClient()  # PvPiClient(timeout_ms=3000) to wait less for each answer
print(client.get_alive())
```

`PvPiClient()` goes through the UART proxy when its service is running, and opens the serial port itself when it isn't.

Check out the [client.py](src/pvpi/client.py) for more details.

