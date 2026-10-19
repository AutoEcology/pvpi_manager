[Home](Home.md)

# Troubleshooting

The services are managed by `systemd`, Linux's service manager. To see if they're running:

```shell
sudo systemctl status pvpi_manager.service
sudo systemctl status pvpi_uart.service
sudo systemctl status pvpi_dashboard.service   # if you added the dashboard
```

To follow what one is doing right now:

```shell
journalctl -u pvpi_manager.service -f
```

(`journalctl` shows the logs `systemd` keeps; [here's a good intro](https://www.digitalocean.com/community/tutorials/how-to-use-journalctl-to-view-and-manipulate-systemd-logs).)

To stop the dashboard and keep it from starting at boot:

```shell
sudo systemctl disable --now pvpi_dashboard.service
```

`pvpi install` leaves a service you've disabled like this disabled.

Back to [Home](Home.md)
