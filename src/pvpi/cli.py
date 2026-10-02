import asyncio
import logging
from datetime import datetime
from pathlib import Path

import click

from pvpi.client import PvPiClient
from pvpi.config import PvPiConfig
from pvpi.logging_ import init_logging
from pvpi.services import system_manager
from pvpi.services.zmq_serial_proxy import ZmqSerialProxy
from pvpi.systemd import config_path as systemd_config_path
from pvpi.systemd import install_systemd, restart_systemd, run_dashboard, uninstall_systemd
from pvpi.transports import SerialInterface

logger = logging.getLogger("pvpi")


@click.group()
@click.option("--verbose", is_flag=True, help="Enable debug logging.")
def cli(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    init_logging(logger=logger, level=level)


@cli.command(short_help="Set Pv Pi MCU clock to match current device clock")
def set_mcu_clock():
    pvpi = PvPiClient()
    pvpi.get_alive()
    pvpi.set_mcu_time()
    logger.info("Current MCU time: %s", pvpi.get_mcu_time())


@cli.command(short_help="Run Pv Pi function test with default parameters")
def connection_test():
    client = PvPiClient()
    logger.info("Running PV PI function test!")
    logger.info("Checking connection...")

    is_alive = client.get_alive()
    client.set_mcu_time()
    mcu_time = client.get_mcu_time()
    logger.info("Alive: %s", is_alive)

    device_name, hw_version, fw_version = client.get_device_version()
    logger.info("Device name: %s, PCB version: %s, Firmware version: %s", device_name, hw_version, fw_version)

    logger.info("Current MCU time: %s", mcu_time)
    logger.info("System time: %s", datetime.now().strftime("%y-%m-%d %H:%M:%S"))

    logger.info("Set PV PI time from system time: %s", client.set_mcu_time())
    logger.info("New MCU time: %s", client.get_mcu_time())

    logger.info("PV PI Setting States...")
    client.set_mppt_state("ON")
    logger.info("PV PI Set MPPT State: ON")
    client.set_ts_state("OFF")
    logger.info("PV PI Set TS State: OFF")
    client.set_charge_state("ON")
    logger.info("PV PI Set Charge State: ON")
    client.set_max_charge_current(10)
    logger.info("PV PI Set MAX Charge Current: 10A")
    client.set_wakeup_voltage(13)
    logger.info("PV PI Set Wakeup Voltage: 13V")

    logger.info("PV PI Charge state code: %s", client.get_charge_state_code())
    logger.info("PV PI Charge state: %s", client.get_charge_state())
    logger.info("PV PI Fault code: %s", client.get_fault_code())
    logger.info("PV PI Fault state: %s", client.get_fault_states())

    logger.info("PV PI Battery and PV input...")
    bat_v = client.get_battery_voltage()
    bat_c = client.get_battery_current()
    bat_soc = client.estimated_soc()
    pv_v = client.get_pv_voltage()
    pv_c = client.get_pv_current()
    temperature = client.get_board_temp()
    logger.info("Battery: %s V, %s A", bat_v, bat_c)
    logger.info("Estimated Battery SoC: %s %%", bat_soc)
    logger.info("PV: %s V, %s A", pv_v, pv_c)
    logger.info("PV PI Temp: %sC", temperature)


@cli.command(short_help="Get Pv Pi Statistics")
def get_stats():
    client = PvPiClient()

    logger.info("PV PI Battery and PV input...")
    bat_v = client.get_battery_voltage()
    bat_c = client.get_battery_current()
    bat_soc = client.estimated_soc()

    pv_v = client.get_pv_voltage()
    pv_c = client.get_pv_current()
    temperature = client.get_board_temp()
    logger.info("Battery: %s V, %s A", bat_v, bat_c)
    logger.info("Estimated Battery SoC: %s %%", bat_soc)

    logger.info("PV: %s V, %s A", pv_v, pv_c)
    logger.info("PV PI Temp: %sC", temperature)


@cli.command(short_help="Get Pv Pi Fault States")
def get_faults():
    client = PvPiClient()
    logger.info("PV PI Fault state: %s", client.get_fault_states())


@cli.command(short_help="Get BQ25756 charging State")
def get_charge_state():
    client = PvPiClient()
    logger.info("BQ25756 Charge state: %s", client.get_charge_state())

@cli.command(short_help="Get PV Pi PCB and Firmwware version")
def get_version():
    client = PvPiClient()
    device_name, hw_version, fw_version = client.get_device_version()
    logger.info("Device name: %s, PCB version: %s, Firmware version: %s", device_name, hw_version, fw_version)
    
@cli.command(short_help="Set the maximum input current for the PV Pi")
@click.option("--current", type=int, required=True, help="Maximum charge current in amps")
def set_input_current(current: int):
    client = PvPiClient()
    client.set_max_input_current(current)
    logger.info("PV Pi max input current set to: %s", current)

@cli.command(short_help="Set the maximum battery charge current for the PV Pi")
@click.option("--current", type=int, required=True, help="Maximum charge current in amps")
def set_charge_current(current: int):
    client = PvPiClient()
    client.set_max_charge_current(current)
    logger.info("PV Pi max battery charge current set to: %s", current)

@cli.command(short_help="Enable/Disable Pv Pi MPPT")
@click.option("--enable", is_flag=True, help="Enable PV Pi MPPT.")
def set_mppt(enable: bool = True):
    state = "ON" if enable else "OFF"
    logger.info("Setting PV PI MPPT "  + state)

    client = PvPiClient()
    client.set_mppt_state(state)
    logger.info("PV PI MPPT State set to " + state)


@cli.command(short_help="Enable/Disable Pv Pi Charging")
@click.option("--enable", is_flag=True, help="Enable PV Pi Charging.")
def set_charging(enable: bool = True):
    state = "ON" if enable else "OFF"
    logger.info("Setting PV PI Charging "  + state)

    client = PvPiClient()
    client.set_charge_state(state)
    logger.info("PV PI Charging State set to " + state)


@cli.command(short_help="Enable/Disable BQ25756 Battery Temperature monitoring.")
@click.option("--enable", is_flag=True, help="Enable BQ25756 Battery Temperature monitoring.")
def set_ts(enable: bool = True):
    state = "ON" if enable else "OFF"
    logger.info("Setting BQ25756 Temperature monitoring "  + state)

    client = PvPiClient()
    client.set_ts_state(state)
    logger.info("BQ25756 Temperature monitoring State set to " + state)


@cli.command()
@click.option("--config", type=click.Path(file_okay=True, dir_okay=False))
def uart_proxy(config: str | None = None):
    _config = PvPiConfig.from_file(path=config)
    serial_interface = SerialInterface(port=_config.uart_port)
    proxy_server = ZmqSerialProxy(serial_interface=serial_interface)
    asyncio.run(proxy_server.run())


@cli.command()
@click.option("--config", type=click.Path(file_okay=True, dir_okay=False))
def manager(config: str | None = None):
    _config = PvPiConfig.from_file(path=config)
    system_manager.run(config=_config)


@cli.command(short_help="Launch the Streamlit web dashboard")
@click.option("--config", type=click.Path(file_okay=True, dir_okay=False))
def dashboard(config: str | None = None):
    run_dashboard(config_path=config)


@cli.command(short_help="Install Pv Pi logger & UART proxy as systemd services")
@click.option(
    "--config",
    type=click.Path(file_okay=True, dir_okay=False),
    help="The config file the services use (made with the defaults if it's not there)",
)
def install(config: str | None = None):
    config_path = Path(config).resolve() if config else None
    install_systemd(config_path=config_path)


@cli.command(short_help="Print the config file the installed services use")
def config_path():
    click.echo(systemd_config_path())


@cli.command(short_help="Uninstall Pv Pi logger & UART proxy as systemd services")
def uninstall():
    uninstall_systemd()

@cli.command(short_help="Restart Pv Pi logger & UART proxy systemd services")
def restart():
    restart_systemd()

if __name__ == "__main__":
    cli()
