import logging
import os
import platform
import subprocess
import sys
from datetime import datetime
from functools import lru_cache

_logger = logging.getLogger(__name__)

_MODEL_PATH = "/proc/device-tree/model"


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
    """Return the default UART port for the detected Raspberry Pi model.

    Standard Raspberry Pi models use ``/dev/ttyAMA0`` (PL011 UART).
    Raspberry Pi Zero variants use ``/dev/ttyS0`` (mini UART).
    A Pi 3 or 4 does too, as Bluetooth has the PL011 UART, unless ``dtoverlay=disable-bt`` gave it
    back to the GPIO pins, when there's no ``/dev/ttyS0``.
    """
    try:
        with open(_MODEL_PATH) as f:
            model = f.read().lower()
        _logger.debug("Detected board model: %s", model.strip())
        if "zero" in model:
            return "/dev/ttyS0"
        if ("raspberry pi 3" in model or "raspberry pi 4" in model) and os.path.exists("/dev/ttyS0"):
            return "/dev/ttyS0"
    except OSError:
        _logger.debug("Could not read %s; falling back to /dev/ttyAMA0", _MODEL_PATH)
    return "/dev/ttyAMA0"


def is_linux() -> bool:
    # fast path
    if sys.platform.startswith("linux"):
        return True

    # paranoia tier
    return os.name == "posix" and platform.system() == "Linux"
