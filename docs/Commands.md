# Commands

Everything below runs as `uv run pvpi <command>` from the pvpi_manager folder. `uv run pvpi --help` lists them, and `--help` after any command explains it.

| Command | What it does |
|---|---|
| `connection-test` | Checks the connection and shows the readings. Also resets the PV Pi to its default settings (see [Getting started](Getting-started.md)) |
| `get-stats` | Battery and solar voltage and current, estimated charge, and board temperature |
| `get-charge-state` | Where the charger is in its charge cycle |
| `get-faults` | Any faults the PV Pi reports |
| `get-version` | The PV Pi's board and firmware version |
| `set-mcu-clock` | Sets the PV Pi's clock from your Pi's. Once is enough with an RTC backup battery; without one, the clock is lost whenever the main battery is disconnected |
| `set-charge-current --current 5` | Maximum battery charge current, 0.4 to 10 A |
| `set-input-current --current 2` | Maximum input current, 0.4 to 8 A |
| `set-mppt --enable` / `--disable` | Turns MPPT on or off |
| `set-charging --enable` / `--disable` | Turns battery charging on or off |
| `set-ts --enable` / `--disable` | Turns battery temperature monitoring on or off |
| `schedule [NAME]` | The next 24 hours of a [schedule](Scheduling.md) |
| `install` | Installs the [services](Services-and-dashboard.md) (`--dashboard` / `--no-dashboard` to add or remove the dashboard) |
| `restart` | Restarts all the installed services |
| `uninstall` | Removes the services |
| `config-path` | Shows which [config](Configuration.md) file the services use |
| `dashboard`, `manager`, `uart-proxy` | Run a service by hand instead of in the background |
