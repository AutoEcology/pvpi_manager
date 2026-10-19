[Home](Home.md)

# Python client

You can install the pvpi_manager into your own project and talk to the PV Pi from there.

```shell
uv add pvpi    # or: pip install pvpi
```

```python
from pvpi import PvPiClient

client = PvPiClient()  # PvPiClient(timeout_ms=3000) to wait less for each answer
print(client.get_alive())
print(client.get_battery_voltage())
```

`PvPiClient()` goes through the UART proxy when its service is running, and opens the serial port itself when it isn't. See [client.py](../src/pvpi/client.py) for everything it can do.

A pip-installed `pvpi install` sets up the [services](Services-and-dashboard.md) from that environment too.

Next: [Troubleshooting](Troubleshooting.md)
