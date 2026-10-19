<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/pvpi_white.png">
    <img src="src/pvpi/services/pvpi.png" alt="PV PI" width="300">
  </picture>
</p>

# pvpi_manager
The official Python SDK for the PV Pi.<br>
The PV Pi (PhotoVoltaic Pi) is the first Raspberry Pi HAT that can power your Pi from a high-capacity 12 V lithium iron phosphate (LiFePO4) battery while charging that battery from a large solar panel. Its onboard microcontroller adds a range of smart features for running your Pi off-grid in remote places.

```shell
git clone https://github.com/AutoEcology/pvpi_manager.git
cd pvpi_manager
uv sync
uv run pvpi connection-test
```

New here? Start with [Getting started](docs/Getting-started.md).

## Docs
- [Home](docs/Home.md)
- [Getting started](docs/Getting-started.md)
- [Services and dashboard](docs/Services-and-dashboard.md)
- [Scheduling](docs/Scheduling.md)
- [Power log](docs/Power-log.md)
- [Configuration](docs/Configuration.md)
- [Commands](docs/Commands.md)
- [Python client](docs/Python-client.md)
- [Troubleshooting](docs/Troubleshooting.md)

## Support
The [User Manual](https://static1.squarespace.com/static/6767a8ab1279321b70138597/t/69dae05a35751f0597eea13b/1775951962539/PV_PI_User_Manual.pdf), the [PV Pi tutorials](https://youtube.com/playlist?list=PLbFaSy7wJeFz2h7MJX0VhsMdpvZVvqfuv&si=jxs1IlyUbiJkMmiR) on YouTube, and the [AutoEcology Discord](https://discord.gg/jhXaSxVU9g).

## Updates
- **2026-10-19**: More comprehensive scheduling, as well as a schedule builder and a power log chart on the dashboard. **Warning:** this breaks old scheduling set-ups: configs with `schedule_time`, `shutdown_time` and `wakeup_time` are refused, so move those times into a [schedule file](docs/Scheduling.md). `set-mppt`, `set-charging` and `set-ts` now need `--enable` or `--disable`, and the UART proxy only accepts connections from the Pi itself.
- **2026-10-07**: Dashboard upgrade, now light-weight enough to run on a Pi Zero. **Warning:** the dashboard is only installed if you ask for it (`pvpi install --dashboard`). If your old dashboard ran as root, run `sudo chown -R $USER: .venv` once before `uv sync`.
- **2026-10-02**: More reliable manager: no shutdown on a single low reading, and it carries on past a bad reading.
