import logging
import os
import pwd
import re
import shutil
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


def _find_bin(name: str) -> Path | None:
    """Find a binary, checking both PATH and the invoking user's home."""
    found = shutil.which(name)
    if found:
        return Path(found)
    # Under sudo, the user's ~/.local/bin may not be on root's PATH
    username = _get_username()
    home = Path(pwd.getpwnam(username).pw_dir)
    candidate = home / ".local/bin" / name
    if candidate.exists():
        return candidate
    return None


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


def _get_pvpi() -> Path:
    """Find the pvpi binary."""
    pvpi = _find_bin("pvpi")
    if pvpi:
        return pvpi
    _logger.error("Could not find pvpi binary on PATH")
    sys.exit(1)


def _get_uv() -> Path:
    """Find the uv binary."""
    uv = _find_bin("uv")
    if uv:
        return uv
    _logger.error("Could not find uv binary on PATH")
    sys.exit(1)


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

    if project_dir:
        uv = _get_uv()
        _logger.info("Detected cloned repo at %s — using uv run", project_dir)

        def make_exec_start(subcmd: str) -> str:
            return f"{uv} run --project {project_dir} pvpi {subcmd}{config_flag}"
    else:
        pvpi = _get_pvpi()
        _logger.info("Installed package detected — using %s", pvpi)

        def make_exec_start(subcmd: str) -> str:
            return f"{pvpi} {subcmd}{config_flag}"

    _logger.info("Installing systemd services for user '%s'", user)
    target_dir = _SYSTEMD_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    # In your systemd.py loop:
    for name in _SERVICES:
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
    for name in _SERVICES:
        subprocess.run(["systemctl", "enable", name], check=True)
        subprocess.run(["systemctl", "restart", name], check=True)
        _logger.info("%s installed & started", name)
    _logger.info("Installation complete!")


def uninstall_systemd() -> None:
    _check_run_requirements()
    target_dir = Path("/etc/systemd/system")
    for name in _SERVICES:
        subprocess.run(["systemctl", "disable", name], check=True)
        dst = target_dir / name
        os.remove(dst)
        _logger.info("%s uninstalled", name)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    _logger.info("Uninstall complete!")


def restart_systemd() -> None:
    _check_run_requirements()
    target_dir = Path("/etc/systemd/system")
    for name in _SERVICES:
        subprocess.run(["systemctl", "restart", name], check=True)
    _logger.info("Restart complete!")


def run_dashboard(config_path: str | None = None) -> None:
    _check_run_requirements()
    uv = _get_uv()
    project_dir = _get_project_dir()
    
    dashboard_script = Path(__file__).parent / "services" / "dashboard.py"
    
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    
    if config_path:
        env["PVPI_CONFIG_PATH"] = str(Path(config_path).resolve())

    cmd = [
        str(uv), "run", "--project", str(project_dir),
        "streamlit", "run", str(dashboard_script),
        "--server.headless", "true",
        "--server.address", "0.0.0.0",
        "--server.port", "8501"
    ]
    
    _logger.info("Launching Streamlit dashboard...")
    subprocess.run(cmd, env=env, check=True)