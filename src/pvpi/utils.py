import logging
import os
import platform
import re
import subprocess
import sys
from datetime import datetime
from functools import lru_cache

_logger = logging.getLogger(__name__)

_MODEL_PATH = "/proc/device-tree/model"
_SERIAL0 = "/dev/serial0"  # Raspberry Pi OS's link to the primary UART
_PI5 = re.compile(r"raspberry pi (5|500|compute module 5)\b")


def set_system_time(dt: datetime) -> bool:
    """Set host machine's (Raspberry Pi's) clock from datetime object. Needs `root` privileges."""
    try:
        time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        subprocess.run(["sudo", "date", "-s", time_str], check=True)
        return True
    except Exception:
        _logger.exception("Failed to set system time")
        return False


@lru_cache(maxsize=1)
def default_uart_port() -> str:
    """Return the UART on GPIO 14 and 15 for the detected Raspberry Pi model.

    Raspberry Pi OS links ``/dev/serial0`` to it, following ``dtoverlay=disable-bt`` and
    ``miniuart-bt``, except on a Pi 5, where ``/dev/serial0`` is the debug header and GPIO 14 and 15
    are ``/dev/ttyAMA0``. Without the link (another OS): ``/dev/ttyS0`` (the mini UART) on a Pi Zero,
    3 or 4, else ``/dev/ttyAMA0``.
    """
    try:
        with open(_MODEL_PATH) as f:
            model = f.read().lower()
    except OSError:
        _logger.debug("Could not read %s; falling back to /dev/ttyAMA0", _MODEL_PATH)
        return "/dev/ttyAMA0"
    _logger.debug("Detected board model: %s", model.strip("\0\n "))
    if _PI5.search(model):
        return "/dev/ttyAMA0"
    if os.path.exists(_SERIAL0):
        return os.path.realpath(_SERIAL0)
    if "zero" in model or "raspberry pi 3" in model or "raspberry pi 4" in model:
        return "/dev/ttyS0"
    return "/dev/ttyAMA0"


def is_linux() -> bool:
    # fast path
    if sys.platform.startswith("linux"):
        return True

    # paranoia tier
    return os.name == "posix" and platform.system() == "Linux"
