# Getting started

pvpi_manager runs on Raspberry Pi compatible boards. It's been tested on a Pi 5 (Raspberry Pi OS 64-bit, 2025-12-04) and a Pi Zero 2 W.

## 1. Install uv

[uv](https://docs.astral.sh/uv) is the Python package manager we use:

```shell
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 2. Turn on the UART

The PV Pi talks to your Pi over the serial port on GPIO 14/15, which is off by default. Run `sudo raspi-config`, then:

1. `3 Interface Options` → `I6 Serial Port`
2. "No" to a login shell over serial
3. "Yes" to enabling the serial port hardware
4. Exit and reboot

pvpi_manager picks the right port for your board (`/dev/ttyAMA0`, or `/dev/ttyS0` on a Pi Zero).

- On a Pi 5 you can instead add `dtparam=uart0=on` to `/boot/firmware/config.txt` and reboot.
- On a Pi 3 or 4, Bluetooth uses `/dev/ttyAMA0` unless `dtoverlay=disable-bt` is in `/boot/firmware/config.txt`. Otherwise set `uart_port` to `/dev/ttyS0` in the [config](Configuration.md).

## 3. Turn off the sudo password

pvpi_manager needs `sudo` to shut your Pi down (and to set its clock when `time_mcu2pi` is on), so sudo has to work without a password. Run `sudo raspi-config` → `1 System Options` → `S10 Admin Password` → "No".

## 4. Install pvpi_manager

```shell
git clone https://github.com/AutoEcology/pvpi_manager.git
cd pvpi_manager
uv sync
uv run pvpi
```

Then check it can see your PV Pi:

```shell
uv run pvpi connection-test
```

This shows your PV Pi's readings. It also resets the PV Pi to its default settings: its clock from the Pi's, MPPT on, charging on, battery temperature monitoring off, a 10 A charge current and a 13 V wake-up voltage. (The manager puts the wake-up voltage back to your `wake_up_volt` the next time it starts.)

Next, set up the [services and dashboard](Services-and-dashboard.md).

## Updating

```shell
git pull
uv sync
uv run pvpi restart
```

Coming from an older version whose dashboard ran as root? If `uv sync` stops with "Permission denied" on a `__pycache__` folder, run `sudo chown -R $USER: .venv` once and sync again.
