import importlib.util
import logging
import os
import pwd
import re
import subprocess
import sys
from pathlib import Path

from pvpi.utils import is_linux

SERVICES = ["pvpi_uart.service", "pvpi_manager.service", "pvpi_dashboard.service"]
_SERVICES = SERVICES  # its old name
_SYSTEMD_DIR = Path("/etc/systemd/system")

_logger = logging.getLogger(__name__)


def _get_project_dir() -> Path | None:
    """Return the project root if running from a cloned repo, else None."""
    candidate = Path(__file__).resolve().parent.parent.parent
    if (candidate / "pyproject.toml").exists():
        return candidate
    return None


def _get_username() -> str:
    """Return the real (non-root) username."""
    return os.environ.get("SUDO_USER") or os.getlogin()


def _user_home() -> Path:
    """The real (non-root) user's home, also when running under sudo."""
    return Path(pwd.getpwnam(_get_username()).pw_dir)


def default_config_path() -> Path:
    """Where `pvpi install` puts config.json when it's given none: in the cloned repo, as
    before, or for an installed package the user's config folder (~/.config/pvpi)."""
    project_dir = _get_project_dir()
    if project_dir is not None:
        return project_dir / "config.json"
    return _user_home() / ".config" / "pvpi" / "config.json"


def config_path(systemd_dir: Path = _SYSTEMD_DIR) -> Path:
    """The config.json the installed services use: the --config in the manager service's
    unit, else where `pvpi install` would put it. For other programs to read or change the
    settings the services run with (then restart them, see restart_systemd)."""
    try:
        unit = (systemd_dir / "pvpi_manager.service").read_text()
    except OSError:
        return default_config_path()
    found = re.search(r"^ExecStart=.*--config[= ](\S+)", unit, re.MULTILINE)
    return Path(found.group(1)) if found else default_config_path()


def _venv_pvpi() -> Path:
    """The `pvpi` of the environment this runs in (a cloned repo's .venv, or wherever the
    package is installed): what the services run, with no `uv run` in front of it."""
    return Path(sys.executable).parent / "pvpi"


def dashboard_installed() -> bool:
    """Whether the dashboard's extra (pvpi[dashboard]: streamlit) is installed."""
    return importlib.util.find_spec("streamlit") is not None


def _render_service(name: str, user: str, exec_start: str) -> str:
    """Generate a systemd unit file."""
    if name == "pvpi_uart.service":
        return (
            "[Unit]\n"
            "Description=UART server for communication with the PV PI\n"
            "After=network-online.target\n"
            "Wants=network-online.target\n"
            "\n"
            "[Service]\n"
            "Type=simple\n"
            f"User={user}\n"
            f"Group={user}\n"
            f"ExecStart={exec_start}\n"
            "Restart=always\n"
            "RestartSec=10\n"
            "\n"
            "[Install]\n"
            "WantedBy=default.target\n"
        )

    if name == "pvpi_manager.service":
        return (
            "[Unit]\n"
            "Description=PV PI Manager Service\n"
            "After=pvpi_uart.service\n"
            "Requires=pvpi_uart.service\n"
            "\n"
            "[Service]\n"
            "Type=simple\n"
            f"User={user}\n"
            f"Group={user}\n"
            f"ExecStart={exec_start}\n"
            "Restart=always\n"
            "RestartSec=10\n"
            "\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
        )

    if name == "pvpi_dashboard.service":
        return (
            "[Unit]\n"
            "Description=PV PI Streamlit Dashboard\n"
            "After=pvpi_manager.service\n"
            "\n"
            "[Service]\n"
            "Type=simple\n"
            f"User={user}\n"
            f"Group={user}\n"
            f"ExecStart={exec_start}\n"
            "Restart=always\n"
            "RestartSec=10\n"
            "Environment=PYTHONUNBUFFERED=1\n" # Ensures logs show up in journalctl immediately
            "\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
        )

    raise ValueError(f"unknown service: {name}")


def _save_default_config(path: Path, user: str) -> None:
    """The defaults, owned by the services' user (install runs as root), with its data
    folder in that user's home rather than root's."""
    from platformdirs import user_data_dir

    from pvpi.config import PvPiConfig

    home = _user_home()
    data = Path(user_data_dir("pvpi"))
    try:
        data = home / data.relative_to(Path.home())
    except ValueError:
        pass
    PvPiConfig(data_log_path=data).save(path)
    owner = pwd.getpwnam(user)
    for p in (path, path.parent):
        os.chown(p, owner.pw_uid, owner.pw_gid)


def _check_run_requirements():
    if not is_linux():
        raise OSError("System is not linux")
    if os.geteuid() != 0:
        _logger.warning("sudo required")
        os.execvp("sudo", ["sudo", sys.executable] + sys.argv)


def install_systemd(config_path: Path | None = None) -> None:
    _check_run_requirements()

    user = _get_username()
    project_dir = _get_project_dir()

    # Create default path if no config path provided
    if config_path is None:
        config_path = default_config_path()
    if not config_path.exists():
        _logger.info("Saving default config file at %s", config_path)
        _save_default_config(config_path, user)

    config_flag = f" --config {config_path}" if config_path else ""
    pvpi = _venv_pvpi()
    _logger.info("The services run %s", pvpi)
    if project_dir:
        _logger.info("From the cloned repo at %s: after a git pull, run 'uv sync' then 'pvpi restart'", project_dir)

    def make_exec_start(subcmd: str) -> str:
        return f"{pvpi} {subcmd}{config_flag}"

    services = list(SERVICES)
    if not dashboard_installed():
        services.remove("pvpi_dashboard.service")
        _logger.info(
            "The dashboard isn't installed, so its service is left out: add it with "
            "'uv sync --extra dashboard' (or pip install 'pvpi[dashboard]'), then run pvpi install again"
        )
        _remove_service("pvpi_dashboard.service")

    _logger.info("Installing systemd services for user '%s'", user)
    target_dir = _SYSTEMD_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    for name in services:
        if name == "pvpi_uart.service":
            exec_start = make_exec_start("uart-proxy")
        elif name == "pvpi_manager.service":
            exec_start = make_exec_start("manager")
        elif name == "pvpi_dashboard.service":
            exec_start = make_exec_start("dashboard") 
        else:
            continue    

        (target_dir / name).write_text(_render_service(name, user, exec_start))

    # Start systemd services
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    for name in services:
        subprocess.run(["systemctl", "enable", name], check=True)
        subprocess.run(["systemctl", "restart", name], check=True)
        _logger.info("%s installed & started", name)
    _logger.info("Installation complete!")


def _remove_service(name: str) -> None:
    """Stop, disable and remove an installed service (nothing if it isn't installed)."""
    unit = _SYSTEMD_DIR / name
    if not unit.exists():
        return
    subprocess.run(["systemctl", "disable", "--now", name], check=False)
    unit.unlink()
    _logger.info("%s uninstalled", name)


def _installed_services() -> list[str]:
    return [name for name in SERVICES if (_SYSTEMD_DIR / name).exists()]


def uninstall_systemd() -> None:
    _check_run_requirements()
    for name in SERVICES:
        _remove_service(name)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    _logger.info("Uninstall complete!")


def restart_systemd() -> None:
    _check_run_requirements()
    for name in _installed_services():
        subprocess.run(["systemctl", "restart", name], check=True)
    _logger.info("Restart complete!")


def run_dashboard(config_path: str | None = None) -> None:
    """Run the dashboard in this process (it becomes streamlit): it only reads the CSV logs
    and asks the UART proxy, so it needs neither root nor a second environment."""
    if not dashboard_installed():
        _logger.error("The dashboard isn't installed: uv sync --extra dashboard (or pip install 'pvpi[dashboard]')")
        sys.exit(1)
    dashboard_script = Path(__file__).parent / "services" / "dashboard.py"
    if config_path:
        os.environ["PVPI_CONFIG_PATH"] = str(Path(config_path).resolve())
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(dashboard_script),
        "--server.headless", "true",
        "--server.address", "0.0.0.0",
        "--server.port", "8501",
    ]  # fmt: skip
    _logger.info("Launching Streamlit dashboard...")
    os.execv(sys.executable, cmd)
